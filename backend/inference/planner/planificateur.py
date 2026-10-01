"""Le planificateur : « comment charger ce modèle sur cette machine, maintenant ? ».

Deux fonctions publiques, et rien d'autre :

- `planifier(demande)` rend le meilleur plan tenable, en descendant l'échelle de dégradation jusqu'à
  en trouver un — jamais en remontant ;
- `degrader(demande, plan, cause)` rend, après un échec, un plan **strictement** plus conservateur.

Le module est pur : aucune lecture de disque, aucun appel à NVML, aucun sous-processus. Toutes les
mesures arrivent par `DemandeDeChargement`. C'est ce qui permet de rejouer en test les situations
qui ont fait échouer la v1, sans GPU.
"""

from __future__ import annotations

from loguru import logger
from pydantic import BaseModel, ConfigDict

from backend.core import PlanificationImpossible, RessourceInsuffisante
from backend.inference.planner.budget import avertissements_metadonnees, utilisation_memoire_gpu
from backend.inference.planner.entrees import CauseEchec, DemandeDeChargement, Moteur, TypeCacheKV
from backend.inference.planner.environnement import construire_environnement
from backend.inference.planner.moteur import choisir_moteur, flash_attention_active, vram_apres_ejection
from backend.inference.planner.paliers import NIVEAU_MINIMAL, Palier, niveau_minimum_pour_cause, palier
from backend.inference.planner.plan import BudgetMemoire, EjectionRequise, PlanDeChargement, ValeurJustifiee
from backend.inference.planner.postes_memoire import construire_budget
from backend.inference.planner.reglages import CadreCalcul, Repartition, resoudre_repartition, resoudre_type_kv

# Au-delà de cette part de la RAM libre, le plan reste valide mais le système va commencer à
# évincer du cache disque : l'utilisateur doit le savoir avant de lancer le chargement.
SEUIL_ALERTE_RAM = 0.9


class ContraintesHeritees(BaseModel):
    """Ce qu'un plan échoué interdit au plan suivant. Vide lors d'une planification initiale.

    Deux plafonds plutôt qu'un, parce qu'il y a deux axes de placement : le nombre de couches sur
    GPU, et le nombre de blocs dont les experts y résident. Sans le second, un palier qui compresse
    le cache KV libérerait de la VRAM et se remettrait à charger des experts que l'échec venait de
    faire sortir.
    """

    model_config = ConfigDict(frozen=True)

    plafond_couches: int | None = None
    plafond_experts_gpu: int | None = None
    deport_experts_autorise: bool = True


class _Preparation(BaseModel):
    """Décisions prises avant tout calcul de répartition : moteur, cache, éjections."""

    model_config = ConfigDict(frozen=True)

    cadre: CadreCalcul
    moteur: ValeurJustifiee[Moteur]
    flash_attention: ValeurJustifiee[bool]
    type_kv: ValeurJustifiee[TypeCacheKV]
    ejections: tuple[EjectionRequise, ...]
    avertissements: tuple[str, ...]


def planifier(demande: DemandeDeChargement, *, niveau_minimum: int = 0) -> PlanDeChargement:
    """Plan de chargement tenable le plus proche des préférences, ou `PlanificationImpossible`.

    La boucle ne parcourt l'échelle que vers le bas : un niveau écarté ne sera jamais réessayé plus
    haut. Elle est bornée par la taille de l'échelle, jamais par une condition d'arrêt dynamique.
    """
    derniere_cause: RessourceInsuffisante | None = None
    for niveau in range(max(0, niveau_minimum), NIVEAU_MINIMAL + 1):
        try:
            plan = _planifier_au_niveau(demande, niveau)
        except RessourceInsuffisante as exc:
            derniere_cause = exc
            logger.warning("Niveau {} intenable pour {} : {}", niveau, demande.metadonnees.identifiant, exc.message)
            continue
        logger.info(
            "Plan {} niveau {} : {}/{} couches GPU, contexte {}, cache {}",
            demande.metadonnees.identifiant,
            niveau,
            plan.couches_gpu.valeur,
            plan.couches_totales,
            plan.contexte.valeur,
            plan.type_cache_kv.valeur.value,
        )
        return plan
    raise PlanificationImpossible(
        f"Aucun plan tenable pour {demande.metadonnees.identifiant}, mode minimal compris.",
        details={"niveau_minimum": niveau_minimum, "derniere_cause": str(derniere_cause) if derniere_cause else None},
    )


def degrader(demande: DemandeDeChargement, plan_echoue: PlanDeChargement, cause: CauseEchec) -> PlanDeChargement:
    """Plan strictement plus conservateur que celui qui vient d'échouer.

    Deux garde-fous, tous deux issus de l'escalade mesurée sur la v1 : le départ ne peut pas être
    au-dessus du niveau déjà tenté, et tout candidat qui ne serait pas strictement plus sobre sur
    tous les axes est écarté au profit du palier suivant.
    """
    depart = max(plan_echoue.niveau_degradation + 1, niveau_minimum_pour_cause(cause))
    logger.info(
        "Dégradation de {} depuis le niveau {} (cause {})",
        demande.metadonnees.identifiant,
        depart,
        cause.value,
    )
    contraintes = _contraintes_apres_echec(plan_echoue, cause)
    for niveau in range(depart, NIVEAU_MINIMAL + 1):
        try:
            # Les plafonds hérités empêchent un palier plus compressé de regagner des couches ou des
            # experts sur le GPU : sans eux, la dégradation devrait sauter jusqu'au palier qui coupe
            # brutalement, faute de candidat strictement plus conservateur.
            candidat = _planifier_au_niveau(demande, niveau, contraintes)
        except RessourceInsuffisante as exc:
            logger.warning("Niveau {} écarté : {}", niveau, exc.message)
            continue
        if candidat.est_plus_conservateur_que(plan_echoue):
            return candidat
        logger.warning("Niveau {} pas strictement plus conservateur que le plan échoué : ignoré.", niveau)
    raise PlanificationImpossible(
        f"Plus aucun palier plus conservateur pour {demande.metadonnees.identifiant} après un échec {cause.value}.",
        details={"niveau_echoue": plan_echoue.niveau_degradation, "cause": cause.value},
    )


def _contraintes_apres_echec(plan_echoue: PlanDeChargement, cause: CauseEchec) -> ContraintesHeritees:
    """Ce que l'échec interdit : ni plus de couches, ni plus de groupes d'experts qu'au plan échoué.

    Le déport d'experts n'est abandonné que si le moteur a déclaré ne pas savoir l'appliquer — seule
    cause qui disqualifie la stratégie plutôt que son dimensionnement. Un plan qui n'en portait pas
    n'a pas à le regagner : la dégradation ne change pas d'axe de placement en cours de descente.
    """
    return ContraintesHeritees(
        plafond_couches=plan_echoue.couches_gpu.valeur,
        plafond_experts_gpu=plan_echoue.blocs_experts_gpu,
        deport_experts_autorise=(
            plan_echoue.experts_deportes is not None
            and cause is not CauseEchec.DEPORT_EXPERTS_INDISPONIBLE
        ),
    )


def _planifier_au_niveau(demande: DemandeDeChargement, niveau: int,
                         contraintes: ContraintesHeritees | None = None) -> PlanDeChargement:
    """Construit le plan d'un palier donné, ou lève `RessourceInsuffisante` s'il ne tient pas."""
    preparation = _preparer(demande, palier(niveau), contraintes or ContraintesHeritees())
    repartition = resoudre_repartition(preparation.cadre)
    budget = _budget_du_plan(preparation.cadre, repartition, demande)
    avertissements = (
        preparation.avertissements
        + avertissements_metadonnees(demande.metadonnees)
        + _verifier_ram(demande, budget)
    )
    return _assembler(demande, niveau, preparation, repartition, budget, avertissements)


def _preparer(demande: DemandeDeChargement, palier_actif: Palier,
              contraintes: ContraintesHeritees) -> _Preparation:
    """Moteur, éjections, flash attention et format de cache — tout ce qui précède la répartition."""
    moteur_choisi, avertissements = choisir_moteur(demande.metadonnees, demande.profil, demande.preferences)
    vram_disponible, ejections = vram_apres_ejection(demande.profil)
    flash = flash_attention_active(demande.profil, demande.preferences, moteur_choisi.valeur)
    type_kv = resoudre_type_kv(demande.preferences, palier_actif)
    cadre = CadreCalcul(
        metadonnees=demande.metadonnees,
        preferences=demande.preferences,
        palier=palier_actif,
        moteur=moteur_choisi.valeur,
        type_kv=type_kv.valeur,
        flash_attention=flash.valeur,
        vram_disponible_octets=vram_disponible,
        plafond_couches_externe=contraintes.plafond_couches,
        plafond_experts_gpu_externe=contraintes.plafond_experts_gpu,
        deport_experts_autorise=contraintes.deport_experts_autorise,
    )
    return _Preparation(
        cadre=cadre,
        moteur=moteur_choisi,
        flash_attention=flash,
        type_kv=type_kv,
        ejections=ejections,
        avertissements=avertissements,
    )


def _budget_du_plan(cadre: CadreCalcul, repartition: Repartition, demande: DemandeDeChargement) -> BudgetMemoire:
    """Décomposition mémoire du plan, poste par poste."""
    return construire_budget(
        cadre.metadonnees,
        couches_gpu=repartition.couches_gpu.valeur,
        contexte=repartition.contexte.valeur,
        batch=repartition.batch.valeur,
        type_kv=cadre.type_kv,
        flash_attention=cadre.flash_attention,
        vram_disponible_octets=cadre.vram_disponible_octets,
        ram_disponible_octets=demande.profil.ram_libre_octets,
        ratio_fragmentation=cadre.preferences.ratio_fragmentation,
        octets_experts_hote=repartition.octets_experts_hote,
    )


def _verifier_ram(demande: DemandeDeChargement, budget: BudgetMemoire) -> tuple[str, ...]:
    """Vérifie que les couches restées côté CPU tiennent en RAM hôte.

    Sous WSL2 la RAM visible est plafonnée par défaut à ~50 % de l'hôte : un plan qui déborde ici
    ne se traduit pas par une lenteur mais par un `OOM killer`, d'où l'échec franc.
    """
    requis = budget.ram_requise_octets
    disponible = demande.profil.ram_libre_octets
    if requis > disponible:
        raise RessourceInsuffisante(
            f"Les couches déportées sur CPU réclament {_en_gio(requis)} Gio de RAM, {_en_gio(disponible)} libres.",
            requis_octets=requis,
            disponible_octets=disponible,
            remediation="Fermer des applications, ou relever `memory=` dans .wslconfig sous WSL2.",
        )
    if disponible > 0 and requis / disponible > SEUIL_ALERTE_RAM:
        return (
            f"Le plan occupe {requis / disponible:.0%} de la RAM libre : le système va évincer son cache disque.",
        )
    return ()


def _assembler(demande: DemandeDeChargement, niveau: int, preparation: _Preparation,
               repartition: Repartition, budget: BudgetMemoire,
               avertissements: tuple[str, ...]) -> PlanDeChargement:
    """Assemble le plan final, une fois toutes les valeurs arrêtées et justifiées."""
    total = demande.metadonnees.nombre_couches
    variables, refusees = construire_environnement(
        demande.profil,
        demande.preferences,
        preparation.cadre.moteur,
        couches_cpu=total - repartition.couches_gpu.valeur,
    )
    return PlanDeChargement(
        identifiant_modele=demande.metadonnees.identifiant,
        niveau_degradation=niveau,
        moteur=preparation.moteur,
        couches_gpu=repartition.couches_gpu,
        couches_totales=total,
        experts_deportes=repartition.experts_deportes,
        contexte=repartition.contexte,
        batch=repartition.batch,
        type_cache_kv=preparation.type_kv,
        flash_attention=preparation.flash_attention,
        utilisation_memoire_gpu=_utilisation_vllm(preparation, budget, demande),
        variables_environnement=variables,
        variables_refusees=refusees,
        ejections_requises=preparation.ejections,
        budget=budget,
        avertissements=avertissements,
    )


def _utilisation_vllm(preparation: _Preparation, budget: BudgetMemoire,
                      demande: DemandeDeChargement) -> ValeurJustifiee[float] | None:
    """Fraction de VRAM préallouée par vLLM — sans objet pour llama.cpp, qui raisonne en couches."""
    if preparation.cadre.moteur is not Moteur.VLLM:
        return None
    fraction = utilisation_memoire_gpu(budget, demande.profil.vram_totale_octets)
    return ValeurJustifiee[float](
        valeur=fraction,
        justification=(
            f"Déduite du besoin calculé ({_en_gio(budget.vram_requise_octets)} Gio sur "
            f"{_en_gio(demande.profil.vram_totale_octets)} Gio), et non par tâtonnement après échec."
        ),
    )


def _en_gio(octets: int) -> float:
    """Conversion en gibioctets, arrondie pour les messages destinés à l'utilisateur."""
    return round(octets / (1024**3), 2)
