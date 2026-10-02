"""Sert un serveur MCP stdio (objet `server` d'un `mcp_server.py`) en HTTP « streamable », DANS l'atelier.

Les serveurs `pty-mcp` et `log-watcher-mcp` de Chris sont des serveurs stdio prévus pour l'hôte. Les
lancer sur l'hôte donnerait à l'agent un terminal et des processus HORS de l'atelier — hors de la
frontière de conteneur qui est sa seule vraie barrière. Ils tournent donc ici, leur code monté en
lecture seule, et le backend les atteint par le réseau interne, jeton de l'atelier exigé (repli fermé).

Usage : python mcp_http.py <chemin/mcp_server.py> <port>
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import uvicorn
from loguru import logger
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

_JETON = os.environ.get("ATELIER_JETON", "")
_CHEMINS = frozenset({"/mcp", "/mcp/"})


def charger_serveur(chemin: Path) -> Any:
    """L'objet `server` du module, importé avec son dossier en tête de `sys.path` (comme en stdio)."""
    sys.path.insert(0, str(chemin.parent))
    spec = importlib.util.spec_from_file_location("serveur_mcp_monte", chemin)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Module MCP illisible : {chemin}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.server


async def _repondre(send: Any, statut: int, texte: str) -> None:
    await send({"type": "http.response.start", "status": statut,
                "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
    await send({"type": "http.response.body", "body": texte.encode()})


def application(serveur: Any) -> Any:
    gestionnaire = StreamableHTTPSessionManager(app=serveur)

    @contextlib.asynccontextmanager
    async def cycle() -> Any:
        async with gestionnaire.run():
            yield

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            async with cycle():
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                await receive()
                await send({"type": "lifespan.shutdown.complete"})
            return
        if scope["type"] != "http" or scope["path"] not in _CHEMINS:
            await _repondre(send, 404, "introuvable")
            return
        entetes = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        if not _JETON or entetes.get("x-atelier-jeton") != _JETON:
            await _repondre(send, 401, "jeton de l'atelier requis")
            return
        await gestionnaire.handle_request(scope, receive, send)

    return app


if __name__ == "__main__":
    chemin, port = Path(sys.argv[1]), int(sys.argv[2])
    if not _JETON:
        logger.warning("ATELIER_JETON absent : {} refusera toutes les requêtes.", chemin.parent.name)
    uvicorn.run(application(charger_serveur(chemin)), host="0.0.0.0", port=port, log_level="warning")
