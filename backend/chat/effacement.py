"""Effacement annulable du contexte (`/clear`) : une ancre sur la branche, rien n'est supprimé.

Un effacement pose une ancre = le dernier message de la branche active au moment du clear. Le contexte
envoyé au moteur ne garde que les messages APRÈS l'ancre sur le chemin ; l'historique reste intact
(fil, arbre, exports). Annuler retire l'ancre et tout le chemin revient.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import datetime, timezone

from loguru import logger

from backend.chat import annulation, depot, depot_effacements
from backend.chat.depot_effacements import InfoEffacement
from backend.chat.erreurs import BrancheInvalide, GenerationDejaEnCours
from backend.chat.modeles import MessageChat
from backend.core import EchoHubError

__all__ = [
    "EffacementIntrouvable",
    "InfoEffacement",
    "ancre_active",
    "annuler",
    "apres_effacement",
    "effacer",
    "lister",
]


class EffacementIntrouvable(EchoHubError):
    """L'effacement visé n'existe pas (déjà annulé, ou appartenant à une autre conversation)."""

    code = "effacement_introuvable"
    statut_http = 404
    remediation_defaut = "Recharger la conversation : cet effacement a peut-être déjà été annulé."


def _exiger_inactive(conversation_id: str) -> None:
    """Refuse de toucher au contexte pendant qu'un tour le lit ou l'écrit."""
    if annulation.est_active(conversation_id):
        raise GenerationDejaEnCours(f"Une génération est en cours sur la conversation {conversation_id}.")


def effacer(conversation_id: str) -> InfoEffacement:
    """Pose une ancre sur le dernier message de la branche active. Lève si la branche est vide."""
    depot.exiger_conversation(conversation_id)
    _exiger_inactive(conversation_id)
    feuille = depot.feuille_active(conversation_id)
    if feuille is None:
        raise BrancheInvalide("Rien à effacer : la conversation ne contient encore aucun message.")
    info = InfoEffacement(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        ancre_message_id=feuille,
        cree_le=datetime.now(timezone.utc),
    )
    depot_effacements.enregistrer_effacement(info)
    logger.info("Contexte effacé sur {} (ancre {})", conversation_id, feuille)
    return info


def lister(conversation_id: str) -> list[InfoEffacement]:
    """Effacements actifs dont l'ancre est sur le chemin de la branche active, du plus ancien au plus récent."""
    chemin = {message.id for message in _chemin_actif(conversation_id)}
    return [info for info in depot_effacements.lire_effacements(conversation_id) if info.ancre_message_id in chemin]


def annuler(conversation_id: str, effacement_id: str) -> None:
    """Annule un effacement. Lève `EffacementIntrouvable` (404) ou `GenerationDejaEnCours` (409)."""
    depot.exiger_conversation(conversation_id)
    _exiger_inactive(conversation_id)
    if not depot_effacements.supprimer_effacement(conversation_id, effacement_id):
        raise EffacementIntrouvable(f"Effacement inconnu : {effacement_id}")
    logger.info("Effacement {} annulé sur {}", effacement_id, conversation_id)


def ancre_active(conversation_id: str, chemin_ids: Collection[str]) -> str | None:
    """Ancre du dernier effacement actif situé sur ce chemin, ou `None`."""
    ancres = [info.ancre_message_id for info in depot_effacements.lire_effacements(conversation_id)]
    sur_chemin = [ancre for ancre in ancres if ancre in chemin_ids]
    return sur_chemin[-1] if sur_chemin else None


def apres_effacement(conversation_id: str, chemin: list[MessageChat]) -> list[MessageChat]:
    """Ne garde que les messages du chemin situés APRÈS la dernière ancre active (ancre exclue)."""
    ids = [message.id for message in chemin]
    ancre = ancre_active(conversation_id, ids)
    if ancre is None:
        return chemin
    return chemin[ids.index(ancre) + 1 :]


def _chemin_actif(conversation_id: str) -> list[MessageChat]:
    """Chemin racine → feuille active, vide si la conversation est vide."""
    feuille = depot.feuille_active(conversation_id)
    return [] if feuille is None else depot.chemin_jusqua(conversation_id, feuille)
