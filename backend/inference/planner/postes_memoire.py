"""Décomposition affichable du budget mémoire : chaque octet engagé, et la mesure qui le produit.

Séparé de `budget.py`, qui ne porte que l'arithmétique : ici on ne calcule aucune grandeur nouvelle,
on répartit celles-là en lignes lisibles. C'est ce que l'interface affiche — elle ne recalcule
jamais un poste, elle rend celui-ci.

Un choix structurant : **le poids n'est pas un poste unique dès que la mesure permet de le
découper**. Sur le MoE mesuré, la part dense d'un bloc pèse 15,68 à 19,50 Mio et sa part experts
330 à 364 Mio — un facteur 18. Les additionner dans une seule ligne « poids des couches » est
exactement ce qui a fait raisonner le planificateur en couches entières, alors que seules 8 des
256 matrices d'experts servent à un token donné.
"""

from __future__ import annotations

from backend.inference.planner.budget import (
    besoin_ram_octets,
    couches_attention,
    octets_etat_recurrent,
    octets_kv_par_token_par_couche,
    octets_tampons_calcul,
    poids_par_couche_octets,
)
from backend.inference.planner.entrees import MetadonneesModele, TypeCacheKV
from backend.inference.planner.plan import BudgetMemoire, PosteMemoire


def construire_budget(
    metadonnees: MetadonneesModele,
    *,
    couches_gpu: int,
    contexte: int,
    batch: int,
    type_kv: TypeCacheKV,
    flash_attention: bool,
    vram_disponible_octets: int,
    ram_disponible_octets: int,
    ratio_fragmentation: float,
    octets_experts_hote: int = 0,
    vllm: bool = False,
    reserve_graphes_octets: int = 0,
) -> BudgetMemoire:
    """Décomposition chiffrée et justifiée de la mémoire engagée par le plan, VRAM et RAM."""
    return BudgetMemoire(
        vram_disponible_octets=vram_disponible_octets,
        postes=postes_vram(
            metadonnees,
            couches_gpu=couches_gpu,
            contexte=contexte,
            batch=batch,
            type_kv=type_kv,
            flash_attention=flash_attention,
            ratio_fragmentation=ratio_fragmentation,
            octets_experts_hote=octets_experts_hote,
            vllm=vllm,
            reserve_graphes_octets=reserve_graphes_octets,
        ),
        ram_requise_octets=besoin_ram_octets(
            metadonnees,
            couches_cpu=metadonnees.nombre_couches - couches_gpu,
            contexte=contexte,
            type_kv=type_kv,
            octets_experts_hote=octets_experts_hote,
        ),
        ram_disponible_octets=ram_disponible_octets,
    )


def postes_vram(
    metadonnees: MetadonneesModele,
    *,
    couches_gpu: int,
    contexte: int,
    batch: int,
    type_kv: TypeCacheKV,
    flash_attention: bool,
    ratio_fragmentation: float,
    octets_experts_hote: int = 0,
    vllm: bool = False,
    reserve_graphes_octets: int = 0,
) -> tuple[PosteMemoire, ...]:
    """Postes de VRAM, chacun chiffré et justifié séparément."""
    poids = _postes_poids(metadonnees, couches_gpu, octets_experts_hote)
    porteuses = couches_attention(metadonnees, couches_gpu)
    cache = int(porteuses * contexte * octets_kv_par_token_par_couche(metadonnees, type_kv))
    tampons = octets_tampons_calcul(metadonnees, contexte, batch, flash_attention, vllm=vllm)
    recurrent = octets_etat_recurrent(metadonnees, couches_gpu)
    total = sum(poste.octets for poste in poids) + cache + tampons + recurrent + reserve_graphes_octets
    postes = (
        *poids,
        _poste_cache(metadonnees, porteuses, couches_gpu, contexte, type_kv, cache),
        _poste_tampons(metadonnees, batch, flash_attention, tampons),
    )
    if recurrent:
        postes = (*postes, _poste_recurrent(metadonnees, couches_gpu, porteuses, recurrent))
    if reserve_graphes_octets:
        postes = (*postes, _poste_graphes(reserve_graphes_octets))
    return (*postes, _poste_fragmentation(ratio_fragmentation, int(total * ratio_fragmentation)))


def _poste_graphes(octets: int) -> PosteMemoire:
    """Réserve des graphes CUDA de vLLM : la vitesse de décodage se paie ici, et se voit."""
    return PosteMemoire(
        libelle="Graphes CUDA",
        octets=octets,
        justification="Capture des graphes de décodage (4 séquences au plus) : environ trois fois la "
                      "vitesse du mode eager, mesuré sur ce poste à 46 contre 16 tok/s.",
    )


def _poste_recurrent(
    metadonnees: MetadonneesModele, couches_gpu: int, porteuses: int, octets: int
) -> PosteMemoire:
    """État récurrent des blocs hybrides — nommé dans le plan, parce qu'il ne l'était pas du tout."""
    return PosteMemoire(
        libelle="État récurrent",
        octets=octets,
        justification=(
            f"{couches_gpu - porteuses} bloc(s) sur {couches_gpu} portent un état récurrent au lieu "
            "d'un cache KV. Sa taille ne dépend pas du contexte, mais du nombre de slots ouverts "
            "par le moteur — un seul ici (`--parallel 1`)."
        ),
    )


def _postes_poids(
    metadonnees: MetadonneesModele,
    couches_gpu: int,
    octets_experts_hote: int,
) -> tuple[PosteMemoire, ...]:
    """Poids résidents : un poste unique, ou la décomposition dense / experts quand elle est mesurée."""
    if not (metadonnees.octets_par_bloc and metadonnees.octets_experts_par_bloc):
        octets = int(couches_gpu * poids_par_couche_octets(metadonnees))
        return (_poste_poids_moyen(metadonnees, couches_gpu, octets),)
    retenus = max(0, min(couches_gpu, metadonnees.nombre_couches))
    experts_totaux = sum(metadonnees.octets_experts_par_bloc[:retenus])
    dense = sum(metadonnees.octets_par_bloc[:retenus]) - experts_totaux
    return (
        _poste_dense(retenus, dense),
        _poste_experts(metadonnees, retenus, max(0, experts_totaux - octets_experts_hote), octets_experts_hote),
        _poste_hors_blocs(metadonnees.octets_hors_blocs or 0),
    )


def _poste_poids_moyen(metadonnees: MetadonneesModele, couches_gpu: int, octets: int) -> PosteMemoire:
    """Poste des poids : la justification affiche le calcul, pas seulement son résultat."""
    return PosteMemoire(
        libelle="Poids des couches sur GPU",
        octets=octets,
        justification=(
            f"{couches_gpu} couches x {_en_mo(poids_par_couche_octets(metadonnees))} Mo, "
            f"soit la taille du fichier divisée par ses {metadonnees.nombre_couches} couches réelles."
        ),
    )


def _poste_dense(couches_gpu: int, octets: int) -> PosteMemoire:
    """Part d'un bloc lue INTÉGRALEMENT à chaque token : attention, normes, routeur, expert partagé."""
    return PosteMemoire(
        libelle="Poids dense des blocs sur GPU",
        octets=octets,
        justification=(
            f"{couches_gpu} blocs hors tenseurs d'experts, mesurés bloc par bloc "
            f"({_en_mo(octets / max(couches_gpu, 1))} Mo en moyenne). Cette part est lue en entier à "
            "chaque token : la sortir de la VRAM coûte bien plus cher que d'en sortir des experts."
        ),
    )


def _poste_experts(
    metadonnees: MetadonneesModele,
    couches_gpu: int,
    octets: int,
    octets_hote: int,
) -> PosteMemoire:
    """Part des experts restée en VRAM. C'est elle, et elle seule, que le déport fait varier."""
    actifs = metadonnees.nombre_experts_actifs
    total = metadonnees.nombre_experts
    routage = f"{actifs} experts sur {total} lus par token" if actifs and total else "routage non déclaré"
    complement = f", {_en_mo(octets_hote)} Mo rappelés en mémoire hôte" if octets_hote else ""
    return PosteMemoire(
        libelle="Poids des experts sur GPU",
        octets=octets,
        justification=f"Tenseurs `ffn_*_exps` des {couches_gpu} blocs délégués{complement} — {routage}.",
    )


def _poste_hors_blocs(octets: int) -> PosteMemoire:
    """Tenseurs hors blocs : tête de sortie et embeddings, facturés en VRAM par prudence."""
    return PosteMemoire(
        libelle="Tenseurs hors blocs",
        octets=octets,
        justification=(
            "`output.weight` et `token_embd`, mesurés sur l'index des tenseurs. Mesuré sur le 0.5B, "
            "`token_embd` reste côté hôte : le compter ici sur-provisionne, c'est le sens prudent."
        ),
    )


def _poste_cache(
    metadonnees: MetadonneesModele,
    porteuses: int,
    couches_gpu: int,
    contexte: int,
    type_kv: TypeCacheKV,
    octets: int,
) -> PosteMemoire:
    """Poste du cache KV : c'est lui qui rend le contexte coûteux, il doit être chiffré à part."""
    detail = (
        f"{porteuses} couches d'attention sur les {couches_gpu} déléguées "
        f"(une sur {metadonnees.intervalle_attention_pleine}, mesuré)"
        if metadonnees.intervalle_attention_pleine is not None
        else f"{couches_gpu} couches"
    )
    return PosteMemoire(
        libelle="Cache KV",
        octets=octets,
        justification=(
            f"{contexte} tokens x {detail} x "
            f"{octets_kv_par_token_par_couche(metadonnees, type_kv):.0f} o/token/couche en {type_kv.value}."
        ),
    )


def _poste_tampons(metadonnees: MetadonneesModele, batch: int, flash_attention: bool, octets: int) -> PosteMemoire:
    """Poste des tampons de calcul, dominé par la matrice de scores quand flash attention est absente."""
    complement = (
        "." if flash_attention else ", plus la matrice de scores d'attention (flash attention désactivée)."
    )
    return PosteMemoire(
        libelle="Tampons de calcul",
        octets=octets,
        justification=(
            f"Activations du graphe pour un batch de {batch}, logits sur "
            f"{metadonnees.taille_vocabulaire} tokens{complement}"
        ),
    )


def _poste_fragmentation(ratio: float, octets: int) -> PosteMemoire:
    """Seul poste non dérivé d'une grandeur du modèle : il est signalé comme tel."""
    return PosteMemoire(
        libelle="Réserve de fragmentation",
        octets=octets,
        justification=(
            f"{ratio:.0%} du total alloué, pour la granularité de l'allocateur CUDA. "
            "Valeur par défaut prudente, non mesurée sur cette machine."
        ),
    )


def _en_mo(octets: float) -> int:
    """Conversion en mébioctets pour les justifications lisibles."""
    return int(octets / (1024 * 1024))
