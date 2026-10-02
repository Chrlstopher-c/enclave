"""Compaction MANUELLE (`/compact [instructions]`) : résumer le contexte de la branche, tout de suite.

Même mécanique que la compaction automatique (`compaction.preparer_compaction`), non destructive et
cumulative, mais sans seuil et la queue réduite au minimum — c'est l'utilisateur qui décide. Les
instructions éventuelles sont données au résumeur comme prioritaires (« garde surtout la liste des
endpoints »). Refusée pendant une génération : le moteur est occupé et le contexte bouge.
"""

from __future__ import annotations

from loguru import logger

from backend.chat import annulation, compaction, depot, port_inference
from backend.chat.erreurs import BrancheInvalide, GenerationDejaEnCours
from backend.chat.generation import contexte_de_branche
from backend.chat.modeles import InfoCompaction


async def compacter_maintenant(conversation_id: str, instructions: str = "") -> InfoCompaction:
    """Compacte la branche affichée et persiste la balise. Lève si rien ne peut être replié."""
    if annulation.est_active(conversation_id):
        raise GenerationDejaEnCours("Une génération est en cours : compacter après sa fin.")
    feuille = depot.feuille_active(conversation_id)
    contexte = contexte_de_branche(conversation_id, feuille)
    if not contexte.ancres:
        raise BrancheInvalide("Rien à compacter : la conversation est vide.")
    active = depot.lire_compaction_active(conversation_id, {a.id for a in contexte.ancres})
    resultat = await compaction.preparer_compaction(
        port_inference.obtenir_moteur(), contexte.entete, contexte.ancres, active,
        conversation_id=conversation_id, message_id=contexte.ancres[-1].id,
        forcer=True, consigne=instructions,
    )
    if resultat.info is None:
        raise BrancheInvalide("Compaction impossible : trop peu d'échanges à replier, ou aucun modèle prêt.")
    depot.enregistrer_compaction(resultat.info)
    logger.info("Compaction manuelle de {} : {} messages résumés ({} consigne).", conversation_id,
                resultat.info.nb_messages_resumes, "avec" if instructions.strip() else "sans")
    return resultat.info


__all__ = ["compacter_maintenant"]
