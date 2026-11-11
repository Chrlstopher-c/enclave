"""Routes HTTP des commandes du chat : catalogue et lancement. Le suivi passe par le flux de la conversation.

Le préfixe `/chat` est celui du domaine `chat` : le flux (`GET …/flux`) reste celui de la génération,
la progression d'une commande y circule en `commande`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from backend.chat import depot
from backend.commandes import execution
from backend.commandes.catalogue import CATALOGUE, CommandeDisponible, commande_connue
from backend.core import EchoHubError

routeur = APIRouter(prefix="/chat", tags=["commandes"])

_P = ParamSpec("_P")
_R = TypeVar("_R")


class DemandeCommande(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nom: str = Field(min_length=1, max_length=40)
    arguments: str = Field(default="", max_length=2_000)


def _traduire_erreurs(fonction: Callable[_P, Awaitable[_R]]) -> Callable[_P, Awaitable[_R]]:
    """Convertit les erreurs métier en réponses HTTP, comme le fait le domaine `chat`."""

    @wraps(fonction)
    async def enveloppe(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            return await fonction(*args, **kwargs)
        except EchoHubError as exc:
            logger.warning("{} : {}", fonction.__name__, exc)
            raise HTTPException(status_code=exc.statut_http, detail=exc.to_dict()) from exc

    return enveloppe


@routeur.get("/commandes", response_model=list[CommandeDisponible])
async def lister_commandes() -> list[CommandeDisponible]:
    """Les commandes que le chat sait exécuter : `/compact`, `/clear`."""
    return list(CATALOGUE)


@routeur.post("/conversations/{conversation_id}/commandes")
@_traduire_erreurs
async def lancer_commande(conversation_id: str, corps: DemandeCommande) -> JSONResponse:
    """`/compact` rend 202 et tourne en tâche serveur ; `/clear` rend 200 avec son effacement."""
    depot.exiger_conversation(conversation_id)
    nom = corps.nom.removeprefix("/").strip()
    if commande_connue(nom) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Commande inconnue : /{nom}")
    lancement = await execution.lancer(conversation_id, nom, corps.arguments)
    contenu: dict[str, object] = {"commande_id": lancement.commande_id, "nom": lancement.nom}
    if lancement.effacement is not None:
        contenu["effacement"] = lancement.effacement
        return JSONResponse(status_code=status.HTTP_200_OK, content=contenu)
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=contenu)


__all__ = ["routeur"]
