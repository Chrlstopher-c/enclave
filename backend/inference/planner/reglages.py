"""Résolution des réglages : contexte, batch, cache KV, répartition des couches.

C'est ici que s'applique la règle du plafonnement : une préférence utilisateur plus ambitieuse que
ce que la machine permet est **ramenée au maximum tenable et expliquée** ; une préférence plus
conservatrice que nécessaire est **respectée telle quelle** — y compris sous les planchers par
défaut, qui ne s'appliquent qu'aux valeurs produites par la dégradation.

Arbitrage assumé quand tout ne tient pas : on **conserve le contexte demandé et on renvoie des
couches sur le CPU**, plutôt que l'inverse. C'est ce que fait la configuration de référence mesurée
(29 couches sur 41, contexte 57344, 19,6 tok/s) et cela respecte la demande explicite de
l'utilisateur. Le contexte n'est raboté que si plus aucune couche ne tient sur le GPU.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backend.core import RessourceInsuffisante
from backend.inference.planner.budget import (
    BATCH_DEFAUT,
    BATCH_PLANCHER,
    CONTEXTE_PLANCHER,
    PAS_BATCH,
    PAS_CONTEXTE,
    aligner,
    contexte_maximal,
    couches_gpu_maximales,
    poids_par_couche_octets,
)
from backend.inference.planner.entrees import (
    MetadonneesModele,
    Moteur,
    PreferencesUtilisateur,
    TypeCacheKV,
)
from backend.inference.planner.experts import (
    MesuresExperts,
    PlacementExperts,
    budget_experts_octets,
    justification_deport,
    mesures_experts,
    placer_experts,
)
from backend.inference.planner.paliers import Palier
from backend.inference.planner.plan import ValeurJustifiee


class CadreCalcul(BaseModel):
    """Tout ce dont la résolution a besoin, réuni pour éviter des signatures à huit paramètres."""

    model_config = ConfigDict(frozen=True)

    metadonnees: MetadonneesModele
    preferences: PreferencesUtilisateur
    palier: Palier
    moteur: Moteur
    type_kv: TypeCacheKV
    flash_attention: bool
    vram_disponible_octets: int

    # Plafond hérité d'un plan qui vient d'échouer. Sans lui, un palier qui compresse le cache KV
    # libère de la VRAM et se met à proposer PLUS de couches que le plan échoué : le garde-fou de
    # `est_plus_conservateur_que` l'écarterait, et la dégradation sauterait des paliers utiles.
    plafond_couches_externe: int | None = None

    # Même garde-fou sur l'autre axe de placement : nombre maximal de blocs dont les experts peuvent
    # résider en VRAM. Il vaut pour les deux stratégies — dans la coupe par couches, une couche sur
    # GPU emporte ses experts, donc ce plafond borne aussi le nombre de couches.
    plafond_experts_gpu_externe: int | None = None

    # Faux quand le moteur a déclaré ne pas savoir rappeler des tenseurs en mémoire hôte : la
    # stratégie elle-même est disqualifiée, la redimensionner ne servirait à rien.
    deport_experts_autorise: bool = True


class Repartition(BaseModel):
    """Triplet cohérent contexte / batch / couches, chacun avec sa justification."""

    model_config = ConfigDict(frozen=True)

    contexte: ValeurJustifiee[int]
    batch: ValeurJustifiee[int]
    couches_gpu: ValeurJustifiee[int]

    # Blocs dont les tenseurs d'experts partent en mémoire hôte. `None` = axe sans objet (modèle
    # dense, vLLM, ou stratégie écartée) ; tuple vide = MoE dont tous les experts tiennent en VRAM.
    experts_deportes: ValeurJustifiee[tuple[int, ...]] | None = None
    octets_experts_hote: int = 0


def resoudre_type_kv(preferences: PreferencesUtilisateur, palier: Palier) -> ValeurJustifiee[TypeCacheKV]:
    """Le palier impose le format du cache dès qu'on dégrade ; sinon la préférence s'applique."""
    if palier.type_kv_impose is None or palier.type_kv_impose is preferences.type_cache_kv:
        return ValeurJustifiee[TypeCacheKV](
            valeur=preferences.type_cache_kv,
            justification=f"Format demandé ({preferences.type_cache_kv.value}), tenable dans le budget mémoire.",
        )
    return ValeurJustifiee[TypeCacheKV](
        valeur=palier.type_kv_impose,
        justification=f"Compressé par la dégradation de niveau {palier.niveau} : {palier.resume}",
        plafonnee=True,
        valeur_demandee=preferences.type_cache_kv,
    )


def resoudre_contexte(metadonnees: MetadonneesModele, preferences: PreferencesUtilisateur,
                      palier: Palier) -> ValeurJustifiee[int]:
    """Contexte souhaité, borné par l'entraînement du modèle et réduit par le palier de dégradation."""
    demande = preferences.contexte or metadonnees.contexte_entrainement_max
    borne = min(demande, metadonnees.contexte_entrainement_max)
    plancher = min(CONTEXTE_PLANCHER, borne)
    valeur = max(plancher, aligner(int(borne * palier.facteur_contexte), PAS_CONTEXTE))

    if palier.facteur_contexte < 1.0:
        return ValeurJustifiee[int](
            valeur=valeur,
            justification=f"Réduit par la dégradation de niveau {palier.niveau} : {palier.resume}",
            plafonnee=True,
            valeur_demandee=demande,
        )
    if demande > metadonnees.contexte_entrainement_max:
        return ValeurJustifiee[int](
            valeur=valeur,
            justification=(
                f"Ramené au contexte d'entraînement du modèle ({metadonnees.contexte_entrainement_max} "
                "tokens) : au-delà, les positions n'ont jamais été vues à l'entraînement."
            ),
            plafonnee=True,
            valeur_demandee=demande,
        )
    return ValeurJustifiee[int](valeur=valeur, justification="Contexte demandé, tenable tel quel.")


def resoudre_batch(preferences: PreferencesUtilisateur, palier: Palier, contexte: int) -> ValeurJustifiee[int]:
    """Batch de traitement du prompt, borné par le contexte et réduit par le palier."""
    demande = preferences.batch or BATCH_DEFAUT
    borne = min(demande, contexte)
    plancher = min(BATCH_PLANCHER, borne)
    valeur = max(plancher, aligner(int(borne * palier.facteur_batch), PAS_BATCH))

    if palier.facteur_batch < 1.0:
        justification = f"Réduit par la dégradation de niveau {palier.niveau} : moins de tampons de calcul."
    elif demande > contexte:
        justification = f"Ramené au contexte ({contexte}) : traiter plus de tokens que le contexte n'a pas de sens."
    elif preferences.batch is None:
        justification = f"Défaut amont de llama.cpp ({BATCH_DEFAUT}), borné par le contexte retenu."
    else:
        justification = "Batch demandé, tenable tel quel."
    return ValeurJustifiee[int](
        valeur=valeur,
        justification=justification,
        plafonnee=valeur < demande,
        valeur_demandee=demande,
    )


def plafond_couches(cadre: CadreCalcul) -> int:
    """Plafond hors contrainte mémoire : total du modèle, réduit par le palier puis par l'utilisateur.

    Le plafond d'experts résidents s'y applique aussi : dans la coupe par couches, une couche placée
    sur le GPU y emporte ses tenseurs d'experts. Un plan qui déportait des experts ne peut donc pas
    être suivi d'un plan qui remet ces mêmes experts en VRAM sous couvert de changer d'axe.
    """
    plafond = cadre.metadonnees.nombre_couches
    if cadre.palier.facteur_couches < 1.0:
        plafond = int(plafond * cadre.palier.facteur_couches)
    if cadre.preferences.couches_gpu is not None:
        plafond = min(plafond, cadre.preferences.couches_gpu)
    if cadre.plafond_couches_externe is not None:
        plafond = min(plafond, cadre.plafond_couches_externe)
    return max(0, min(plafond, plafond_residents_experts(cadre)))


def couches_tenables(cadre: CadreCalcul, contexte: int, batch: int) -> int:
    """Couches que la VRAM disponible supporte réellement, cache KV et tampons déduits."""
    return couches_gpu_maximales(
        cadre.metadonnees,
        contexte=contexte,
        batch=batch,
        type_kv=cadre.type_kv,
        flash_attention=cadre.flash_attention,
        vram_disponible_octets=cadre.vram_disponible_octets,
        ratio_fragmentation=cadre.preferences.ratio_fragmentation,
    )


def _justifier_couches(cadre: CadreCalcul, retenues: int, plafond: int, tenables: int) -> ValeurJustifiee[int]:
    """Nombre de couches retenu, accompagné de la contrainte qui l'a réellement décidé."""
    justification, plafonnee, demandee = _origine_couches(cadre, retenues, plafond, tenables)
    return ValeurJustifiee[int](
        valeur=retenues,
        justification=justification,
        plafonnee=plafonnee,
        valeur_demandee=demandee,
    )


def _origine_couches(cadre: CadreCalcul, retenues: int, plafond: int, tenables: int) -> tuple[str, bool, int]:
    """Identifie la contrainte contraignante : VRAM, échec précédent, palier, ou choix utilisateur."""
    total = cadre.metadonnees.nombre_couches
    if tenables < plafond:
        poids_mo = int(poids_par_couche_octets(cadre.metadonnees) / (1024 * 1024))
        return (
            f"{retenues} couches sur {total} : chaque couche pèse {poids_mo} Mo (taille du fichier "
            f"divisée par ses {total} couches réelles), cache KV et tampons compris, la VRAM "
            "disponible ne va pas au-delà.",
            True,
            plafond,
        )
    if cadre.plafond_experts_gpu_externe is not None and retenues >= plafond_residents_experts(cadre):
        return (
            f"Borné à {retenues} couches : le plan précédent gardait {retenues} groupes d'experts en "
            "VRAM et a échoué, une couche remise ici y remettrait aussi ses experts.",
            True,
            total,
        )
    if cadre.plafond_couches_externe is not None and retenues >= cadre.plafond_couches_externe:
        return (
            f"Borné à {retenues} couches : le plan précédent a échoué à ce niveau, une dégradation "
            "ne peut pas en remettre davantage sur le GPU.",
            True,
            total,
        )
    if cadre.palier.facteur_couches < 1.0:
        return (
            f"Réduit par la dégradation de niveau {cadre.palier.niveau} : {cadre.palier.resume}",
            True,
            total,
        )
    if retenues < total:
        return (f"Choix de l'utilisateur : {retenues} couches sur {total}, plus prudent que nécessaire.", False, total)
    return (f"Les {total} couches tiennent en VRAM avec ce contexte : aucun calcul ne part sur le CPU.", False, total)


def resoudre_repartition(cadre: CadreCalcul) -> Repartition:
    """Triplet contexte / batch / couches cohérent avec la VRAM disponible.

    Deux axes de placement, et un seul est retenu par plan : le déport d'experts quand le modèle et
    le moteur le permettent, la coupe par couches entières sinon. Le premier est essayé d'abord —
    quand il s'applique, il libère la même VRAM en laissant l'attention et le dense sur le GPU.
    """
    contexte = resoudre_contexte(cadre.metadonnees, cadre.preferences, cadre.palier)
    batch = resoudre_batch(cadre.preferences, cadre.palier, contexte.valeur)
    if cadre.moteur is Moteur.VLLM:
        return _repartition_vllm(cadre, contexte, batch)

    par_experts = _repartition_experts(cadre, contexte, batch)
    if par_experts is not None:
        return par_experts

    plafond = plafond_couches(cadre)
    tenables = couches_tenables(cadre, contexte.valeur, batch.valeur)
    if tenables > 0 or plafond == 0:
        retenues = min(plafond, tenables)
        return Repartition(
            contexte=contexte,
            batch=batch,
            couches_gpu=_justifier_couches(cadre, retenues, plafond, tenables),
        )
    return _repartition_contexte_raccourci(cadre, contexte, batch, plafond)


def strategie_experts_applicable(cadre: CadreCalcul) -> bool:
    """Vrai si le déport d'experts a un sens ici : rien d'autre ne réclame moins de couches sur GPU.

    On interroge les SOURCES du plafond de couches, pas le plafond hérité d'un échec : celui-ci
    borne les experts résidents, il ne doit pas faire abandonner la stratégie qui l'a produit.
    """
    if not cadre.deport_experts_autorise or cadre.moteur is not Moteur.LLAMA_CPP:
        return False
    if cadre.palier.facteur_couches < 1.0:
        return False
    demande = cadre.preferences.couches_gpu
    return demande is None or demande >= cadre.metadonnees.nombre_couches


def plafond_residents_experts(cadre: CadreCalcul) -> int:
    """Nombre maximal de blocs dont les experts peuvent rester en VRAM."""
    total = cadre.metadonnees.nombre_couches
    if cadre.plafond_experts_gpu_externe is None:
        return total
    return max(0, min(total, cadre.plafond_experts_gpu_externe))


def _repartition_experts(cadre: CadreCalcul, contexte: ValeurJustifiee[int],
                         batch: ValeurJustifiee[int]) -> Repartition | None:
    """Toutes les couches sur GPU, seuls des groupes d'experts en RAM — ou `None` si inapplicable.

    Rend `None` sans rien tenter quand la mesure manque ou quand le socle lui-même ne tient pas :
    dans ce dernier cas, déporter la totalité des experts ne suffirait pas et la coupe par couches
    reste le seul levier.
    """
    if not strategie_experts_applicable(cadre):
        return None
    mesures = mesures_experts(cadre.metadonnees)
    if mesures is None:
        return None
    budget = _budget_experts(cadre, mesures, contexte.valeur, batch.valeur)
    if budget <= 0:
        return None
    placement = placer_experts(
        mesures,
        budget_octets=budget,
        plafond_residents=plafond_residents_experts(cadre),
    )
    return Repartition(
        contexte=contexte,
        batch=batch,
        couches_gpu=_couches_avec_deport(cadre.metadonnees.nombre_couches, placement),
        experts_deportes=_justifier_deport(cadre, mesures, placement),
        octets_experts_hote=placement.octets_hote,
    )


def _budget_experts(cadre: CadreCalcul, mesures: MesuresExperts, contexte: int, batch: int) -> float:
    """VRAM laissée aux experts par ce cadre — le reste du cadre n'est que du transport d'arguments."""
    return budget_experts_octets(
        cadre.metadonnees,
        mesures,
        contexte=contexte,
        batch=batch,
        type_kv=cadre.type_kv,
        flash_attention=cadre.flash_attention,
        vram_disponible_octets=cadre.vram_disponible_octets,
        ratio_fragmentation=cadre.preferences.ratio_fragmentation,
    )


def _couches_avec_deport(total: int, placement: PlacementExperts) -> ValeurJustifiee[int]:
    """Le nombre de couches cesse de décrire le placement : la justification doit le dire."""
    return ValeurJustifiee[int](
        valeur=total,
        justification=(
            f"Les {total} blocs restent sur le GPU : ce sont {placement.nombre_deportes} groupes de "
            "tenseurs d'experts qui partent en mémoire hôte, pas des couches entières. Toute "
            "l'attention et tout le dense restent accélérés."
        ),
    )


def _justifier_deport(cadre: CadreCalcul, mesures: MesuresExperts,
                      placement: PlacementExperts) -> ValeurJustifiee[tuple[int, ...]]:
    """Axe de placement des experts, avec sa mesure. Plafonné quand un échec précédent le borne."""
    plafond = cadre.plafond_experts_gpu_externe
    borne = plafond is not None and mesures.nombre_blocs - placement.nombre_deportes >= plafond
    justification = justification_deport(cadre.metadonnees, mesures, placement)
    if borne:
        justification += (
            f" Borné à {plafond} groupes en VRAM : le plan précédent a échoué à ce niveau, "
            "une dégradation ne peut pas en remettre davantage."
        )
    return ValeurJustifiee[tuple[int, ...]](
        valeur=placement.blocs_deportes,
        justification=justification,
        plafonnee=borne,
    )


def _repartition_contexte_raccourci(cadre: CadreCalcul, contexte: ValeurJustifiee[int],
                                    batch: ValeurJustifiee[int], plafond: int) -> Repartition:
    """Aucune couche ne tient au contexte demandé : on raccourcit le contexte plutôt que de tout basculer CPU.

    Si même une seule couche ne tient pas à un contexte utilisable, le plan reste valide en pur CPU —
    llama.cpp sait le faire, et c'est plus honnête que de refuser le chargement.
    """
    plafond_ctx = contexte_maximal(
        cadre.metadonnees,
        couches_gpu=1,
        batch=batch.valeur,
        type_kv=cadre.type_kv,
        flash_attention=cadre.flash_attention,
        vram_disponible_octets=cadre.vram_disponible_octets,
        ratio_fragmentation=cadre.preferences.ratio_fragmentation,
    )
    if plafond_ctx < min(CONTEXTE_PLANCHER, contexte.valeur):
        return _repartition_tout_cpu(contexte, batch, plafond)
    reduit = min(contexte.valeur, plafond_ctx)
    batch_reduit = resoudre_batch(cadre.preferences, cadre.palier, reduit)
    tenables = couches_tenables(cadre, reduit, batch_reduit.valeur)
    return Repartition(
        contexte=_contexte_raccourci(contexte, reduit),
        batch=batch_reduit,
        couches_gpu=_justifier_couches(cadre, min(plafond, tenables), plafond, tenables),
    )


def _contexte_raccourci(contexte: ValeurJustifiee[int], reduit: int) -> ValeurJustifiee[int]:
    """Annonce un raccourcissement seulement s'il a lieu.

    Sur une architecture hybride, une couche isolée peut ne porter aucun cache KV : le plafond de
    contexte est alors le contexte d'entraînement, et rien n'est raboté. Annoncer « raccourci de
    32768 à 32768 » ferait passer une absence de contrainte pour un plafonnement.
    """
    if reduit >= contexte.valeur:
        return contexte
    return ValeurJustifiee[int](
        valeur=reduit,
        justification=(
            f"Raccourci de {contexte.valeur} à {reduit} tokens : au contexte demandé, le cache KV "
            "consommait toute la VRAM et aucune couche n'aurait été accélérée."
        ),
        plafonnee=True,
        valeur_demandee=contexte.valeur,
    )


def _repartition_tout_cpu(contexte: ValeurJustifiee[int], batch: ValeurJustifiee[int],
                          plafond: int) -> Repartition:
    """Plan sans accélération GPU : llama.cpp sait le faire, et c'est plus honnête qu'un refus."""
    return Repartition(
        contexte=contexte,
        batch=batch,
        couches_gpu=ValeurJustifiee[int](
            valeur=0,
            justification="Aucune couche ne tient en VRAM, même au contexte plancher : exécution entièrement CPU.",
            plafonnee=True,
            valeur_demandee=plafond,
        ),
    )


def _repartition_vllm(cadre: CadreCalcul, contexte: ValeurJustifiee[int],
                      batch: ValeurJustifiee[int]) -> Repartition:
    """vLLM ne sait pas déporter une partie des couches : c'est tout en VRAM, ou pas de plan."""
    total = cadre.metadonnees.nombre_couches
    plafond_ctx = contexte_maximal(
        cadre.metadonnees,
        couches_gpu=total,
        batch=batch.valeur,
        type_kv=cadre.type_kv,
        flash_attention=cadre.flash_attention,
        vram_disponible_octets=cadre.vram_disponible_octets,
        ratio_fragmentation=cadre.preferences.ratio_fragmentation,
    )
    if plafond_ctx < min(CONTEXTE_PLANCHER, contexte.valeur):
        raise RessourceInsuffisante(
            f"vLLM exige les {total} couches en VRAM ; le modèle n'y tient pas, même au contexte plancher.",
            requis_octets=int(cadre.metadonnees.taille_octets),
            disponible_octets=cadre.vram_disponible_octets,
            remediation="Choisir une quantification plus basse, ou un modèle GGUF chargeable par llama.cpp.",
        )
    if plafond_ctx >= contexte.valeur:
        return Repartition(contexte=contexte, batch=batch, couches_gpu=_couches_vllm(total, contexte.valeur))
    return _repartition_vllm_reduite(cadre, contexte, plafond_ctx)


def _repartition_vllm_reduite(cadre: CadreCalcul, contexte: ValeurJustifiee[int], reduit: int) -> Repartition:
    """Les poids sont incompressibles sous vLLM : seul le contexte peut absorber le manque de VRAM."""
    contexte_reduit = ValeurJustifiee[int](
        valeur=reduit,
        justification=(
            f"Raccourci de {contexte.valeur} à {reduit} tokens : vLLM prééalloue la totalité du modèle, "
            "le contexte est ce qu'il reste de VRAM une fois les poids placés."
        ),
        plafonnee=True,
        valeur_demandee=contexte.valeur,
    )
    return Repartition(
        contexte=contexte_reduit,
        batch=resoudre_batch(cadre.preferences, cadre.palier, reduit),
        couches_gpu=_couches_vllm(cadre.metadonnees.nombre_couches, reduit),
    )


def _couches_vllm(total: int, contexte: int) -> ValeurJustifiee[int]:
    return ValeurJustifiee[int](
        valeur=total,
        justification=(
            f"vLLM charge les {total} couches en VRAM sans répartition possible ; l'ajustement porte "
            f"sur le contexte, ici {contexte} tokens."
        ),
    )
