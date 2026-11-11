"""Routes des effacements de contexte (`/clear`). Montées par `routes.py`.

Même traduction d'erreurs que `routes.py` : toute `EchoHubError` devient une réponse HTTP via
`statut_http` et `to_dict()`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from fastapi import APIRouter, HTTPException, Response, status
from loguru import logger

from backend.chat import effacement
from backend.chat.depot_effacements import InfoEffacement
from backend.core import EchoHubError

# Sans préfixe : `routes.py` l'inclut dans son propre routeur, qui applique `/chat`.
routeur = APIRouter(tags=["chat"])

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _traduire_erreurs(fonction: Callable[_P, Awaitable[_R]]) -> Callable[_P, Awaitable[_R]]:
    """Convertit les erreurs métier en réponses HTTP, en préservant la signature vue par FastAPI."""

    @wraps(fonction)
    async def enveloppe(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            return await fonction(*args, **kwargs)
        except EchoHubError as exc:
            logger.warning("{} : {}", fonction.__name__, exc)
            raise HTTPException(status_code=exc.statut_http, detail=exc.to_dict()) from exc

    return enveloppe


@routeur.get("/conversations/{conversation_id}/effacements", response_model=list[InfoEffacement])
@_traduire_erreurs
async def lister_effacements(conversation_id: str) -> list[InfoEffacement]:
    """Effacements actifs de la branche affichée, du plus ancien au plus récent."""
    return effacement.lister(conversation_id)


@routeur.delete("/conversations/{conversation_id}/effacements/{effacement_id}", status_code=204)
@_traduire_erreurs
async def annuler_effacement(conversation_id: str, effacement_id: str) -> Response:
    """Annule un effacement : tout le chemin redevient visible pour le moteur."""
    effacement.annuler(conversation_id, effacement_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
