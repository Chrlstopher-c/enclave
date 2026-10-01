"""Frontière unique entre le vocabulaire du planificateur et celui des moteurs.

Le planificateur produit un `PlanDeChargement` riche : chaque valeur y est accompagnée de sa
justification, et le budget mémoire y est détaillé poste par poste. Les moteurs, eux, n'ont besoin
que des valeurs. Traduire ici, et nulle part ailleurs, préserve deux propriétés :

- les adaptateurs restent testables sans planificateur — ils ne connaissent que `PlanChargement` ;
- il n'existe qu'un seul endroit où une valeur du plan peut être mal recopiée, donc un seul endroit
  à relire quand un paramètre appliqué ne correspond pas au plan affiché.

Aucune valeur n'est calculée ni complétée ici : ce module recopie et renomme, rien d'autre. Une
valeur absente du plan reste absente, et c'est l'adaptateur qui refusera le plan.
"""

from __future__ import annotations

from backend.inference.engines_adapters.contrat import CauseEchec, MoteurSupporte, PlanChargement
from backend.inference.planner import CauseEchec as CausePlanificateur
from backend.inference.planner import PlanDeChargement

# Une cause d'échec moteur ne choisit pas un plan : elle choisit le levier de dégradation. Le
# planificateur n'a donc besoin que d'une famille, pas de la cause exacte.
_CAUSES_VERS_PLANIFICATEUR: dict[CauseEchec, CausePlanificateur] = {
    CauseEchec.VRAM_INSUFFISANTE: CausePlanificateur.MEMOIRE_GPU_INSUFFISANTE,
    CauseEchec.VRAM_NON_LIBEREE: CausePlanificateur.MEMOIRE_GPU_INSUFFISANTE,
    CauseEchec.RAM_INSUFFISANTE: CausePlanificateur.MEMOIRE_HOTE_INSUFFISANTE,
    CauseEchec.CONTEXTE_TROP_GRAND: CausePlanificateur.CONTEXTE_REFUSE,
    CauseEchec.MOTEUR_ABSENT: CausePlanificateur.MOTEUR_INDISPONIBLE,
    CauseEchec.MOTEUR_SANS_CUDA: CausePlanificateur.MOTEUR_INDISPONIBLE,
    # Seule cause qui disqualifie un axe de placement plutôt qu'un dimensionnement : le planificateur
    # doit abandonner le déport d'experts, pas simplement en déporter davantage.
    CauseEchec.DEPORT_EXPERTS_INDISPONIBLE: CausePlanificateur.DEPORT_EXPERTS_INDISPONIBLE,
}


def vers_plan_moteur(plan: PlanDeChargement, chemin_modele: str) -> PlanChargement:
    """Convertit un plan planifié en plan applicable par un adaptateur.

    `chemin_modele` vient de l'appelant : le planificateur raisonne sur un identifiant de modèle,
    la résolution vers un chemin de fichier appartient au domaine `models`.
    """
    return PlanChargement(
        moteur=MoteurSupporte(plan.moteur.valeur.value),
        chemin_modele=chemin_modele,
        identifiant_modele=plan.identifiant_modele,
        couches_gpu=plan.couches_gpu.valeur,
        experts_deportes=list(plan.experts_deportes.valeur) if plan.experts_deportes else [],
        contexte=plan.contexte.valeur,
        batch=plan.batch.valeur,
        type_kv_cache=plan.type_cache_kv.valeur.value,
        flash_attention=plan.flash_attention.valeur,
        fraction_vram=plan.utilisation_memoire_gpu.valeur if plan.utilisation_memoire_gpu else None,
        variables_env=plan.environnement,
        justifications=list(plan.justifications()),
    )


def vers_cause_planificateur(cause: CauseEchec | None) -> CausePlanificateur:
    """Traduit une cause d'échec moteur en cause de dégradation. L'inconnu reste inconnu."""
    if cause is None:
        return CausePlanificateur.INCONNUE
    return _CAUSES_VERS_PLANIFICATEUR.get(cause, CausePlanificateur.INCONNUE)
