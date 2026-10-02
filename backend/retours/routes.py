"""API HTTP des retours : noter une réponse, lire les verdicts, exporter le jeu pour l'entraînement."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from backend.retours import depot, service
from backend.retours.modeles import DemandeRetour, ResumeRetours, Retour, Source

PREFIXE = "/retours"
routeur = APIRouter(prefix=PREFIXE, tags=["retours"])


@routeur.post("", response_model=Retour)
def noter(demande: DemandeRetour) -> Retour:
    """Enregistre (ou remplace) le verdict porté sur une réponse du modèle."""
    return service.noter(demande)


@routeur.get("", response_model=ResumeRetours)
def resumer(conversation_id: str | None = Query(default=None)) -> ResumeRetours:
    """Compteurs et verdict par message, pour une conversation ou pour tout le journal."""
    return service.resumer(conversation_id)


@routeur.delete("/{message_id}")
def retirer(message_id: str, source: Source = Query(default="chris")) -> dict[str, bool]:
    if not depot.supprimer(message_id, source):
        raise HTTPException(status_code=404, detail="Aucun retour sur ce message.")
    return {"supprime": True}


@routeur.get("/export.jsonl", response_class=PlainTextResponse)
def exporter() -> str:
    """Tous les retours, une ligne JSON par réponse notée : l'entrée du réentraînement."""
    return "".join(r.model_dump_json() + "\n" for r in depot.lister())
