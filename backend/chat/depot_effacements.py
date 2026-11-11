"""Persistance des effacements (`/clear`) : une ligne = une ancre posée sur une branche.

La table `chat_effacements` est créée par `depot._SCHEMA_CHAT_SQL` (ajout additif, comme
`chat_compactions`). Annuler un effacement supprime sa ligne : il n'existe pas d'historique des clears.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from loguru import logger
from pydantic import BaseModel

from backend.core import ErreurPersistance, execute, fetch_all


class InfoEffacement(BaseModel):
    """Une ancre de `/clear` : le contexte repart après `ancre_message_id` sur la branche active."""

    id: str
    conversation_id: str
    ancre_message_id: str
    cree_le: datetime

_SELECT_EFFACEMENTS = (
    "SELECT id, conversation_id, ancre_message_id, cree_le FROM chat_effacements"
    " WHERE conversation_id = ? ORDER BY cree_le ASC, rowid ASC"
)

_INSERT_EFFACEMENT = (
    "INSERT INTO chat_effacements (id, conversation_id, ancre_message_id, cree_le) VALUES (?, ?, ?, ?)"
)


def lire_effacements(conversation_id: str) -> list[InfoEffacement]:
    """Tous les effacements de la conversation, du plus ancien au plus récent."""
    return fetch_all(InfoEffacement, _SELECT_EFFACEMENTS, (conversation_id,))


def enregistrer_effacement(info: InfoEffacement) -> None:
    """Persiste une ancre. Lève `ErreurPersistance` si l'écriture échoue."""
    try:
        execute(_INSERT_EFFACEMENT, (info.id, info.conversation_id, info.ancre_message_id, info.cree_le.isoformat()))
    except sqlite3.Error as exc:
        logger.error("Effacement non persisté sur {} : {}", info.conversation_id, exc)
        raise ErreurPersistance("Écriture de l'effacement impossible.", details={"cause": str(exc)}) from exc


def supprimer_effacement(conversation_id: str, effacement_id: str) -> bool:
    """Retire un effacement. Retourne `False` s'il n'existait pas dans cette conversation."""
    try:
        return execute(
            "DELETE FROM chat_effacements WHERE conversation_id = ? AND id = ?",
            (conversation_id, effacement_id),
        ) > 0
    except sqlite3.Error as exc:
        logger.error("Effacement non annulé sur {} : {}", conversation_id, exc)
        raise ErreurPersistance("Annulation de l'effacement impossible.", details={"cause": str(exc)}) from exc
