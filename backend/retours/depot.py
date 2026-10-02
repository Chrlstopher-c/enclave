"""Persistance des retours : une ligne par message noté, le dernier verdict l'emporte.

Table propre au domaine, créée de façon additive et idempotente. Chaque ligne est autonome
(prompt système, historique, réponse) : supprimer la conversation ne fait pas perdre l'exemple.
"""

from __future__ import annotations

import json

from loguru import logger
from pydantic import BaseModel

from backend.core import execute, fetch_all, maintenant
from backend.retours.modeles import Retour, TourHistorique, Verdict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS retours (
    message_id      TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    parent_id       TEXT,
    modele_id       TEXT,
    prompt_systeme  TEXT NOT NULL,
    temperature     REAL,
    historique      TEXT NOT NULL,
    tour            INTEGER NOT NULL DEFAULT 0,
    reponse         TEXT NOT NULL,
    verdict         TEXT NOT NULL,
    correction      TEXT,
    raisons         TEXT NOT NULL DEFAULT '[]',
    cree_le         TEXT NOT NULL
)
"""


class _Ligne(BaseModel):
    message_id: str
    conversation_id: str
    parent_id: str | None
    modele_id: str | None
    prompt_systeme: str
    temperature: float | None
    historique: str
    tour: int
    reponse: str
    verdict: Verdict
    correction: str | None
    raisons: str
    cree_le: str


def assurer_schema() -> None:
    execute(_SCHEMA)


def enregistrer(retour: Retour) -> Retour:
    assurer_schema()
    historique = json.dumps([t.model_dump() for t in retour.historique], ensure_ascii=False)
    retour = retour.model_copy(update={"cree_le": maintenant()})
    execute(
        "INSERT OR REPLACE INTO retours (message_id, conversation_id, parent_id, modele_id, prompt_systeme, "
        "temperature, historique, tour, reponse, verdict, correction, raisons, cree_le) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (retour.message_id, retour.conversation_id, retour.parent_id, retour.modele_id, retour.prompt_systeme,
         retour.temperature, historique, retour.tour, retour.reponse, retour.verdict, retour.correction,
         json.dumps(retour.raisons), retour.cree_le),
    )
    logger.info("Retour {} enregistré sur le message {}", retour.verdict, retour.message_id)
    return retour


def _depuis_ligne(ligne: _Ligne) -> Retour:
    tours = [TourHistorique(**t) for t in json.loads(ligne.historique)]
    return Retour(**{**ligne.model_dump(), "historique": tours, "raisons": json.loads(ligne.raisons)})


def lister(conversation_id: str | None = None) -> list[Retour]:
    assurer_schema()
    if conversation_id is None:
        lignes = fetch_all(_Ligne, "SELECT * FROM retours ORDER BY cree_le")
    else:
        lignes = fetch_all(_Ligne, "SELECT * FROM retours WHERE conversation_id = ? ORDER BY cree_le",
                           (conversation_id,))
    return [_depuis_ligne(ligne) for ligne in lignes]


def retirer_chez_les_freres(parent_id: str | None, verdict: Verdict, sauf: str) -> int:
    """Un seul « meilleure » et un seul « pire » par tour : la nouvelle désignation remplace l'ancienne."""
    assurer_schema()
    return execute("DELETE FROM retours WHERE parent_id IS ? AND verdict = ? AND message_id != ?",
                   (parent_id, verdict, sauf))


def supprimer(message_id: str) -> bool:
    assurer_schema()
    return execute("DELETE FROM retours WHERE message_id = ?", (message_id,)) > 0
