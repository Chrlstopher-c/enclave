"""Relais d'aperçu — l'app qu'un agent fait tourner dans l'atelier, ouverte dans le navigateur.

Les serveurs de dev lancés par `serveur_fond` écoutent DANS le conteneur, sur un port que l'hôte ne
voit pas. Ce relais écoute sur un port unique publié (8090 → hôte 127.0.0.1) et transmet tout ce
qu'il reçoit au port désigné par le backend (`pointer`). L'app est servie À LA RACINE : ses chemins
absolus (`/api/…`, `/assets/…`) marchent tels quels, ce qu'un préfixe d'URL aurait cassé.

Limite assumée : pas de WebSocket (le rechargement à chaud de Vite ne passe pas ; recharger la page).
"""

from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from loguru import logger

PORT_APERCU = 8090
PORTS_RESERVES = frozenset({8080, PORT_APERCU})
_SAUT_PAR_SAUT = frozenset({"connection", "keep-alive", "transfer-encoding", "upgrade", "host",
                            "content-length", "content-encoding"})
_TCP = (Path("/proc/net/tcp"), Path("/proc/net/tcp6"))
_LISTEN = "0A"
# 127.0.0.11, en hexadécimal petit-boutiste : le DNS embarqué de Docker, qui n'est pas une app.
_DNS_DOCKER = "0B00007F"

_cible: dict[str, int | None] = {"port": None}

app = FastAPI(title="EchoHub atelier — aperçu", docs_url=None, redoc_url=None, openapi_url=None)


def pointer(port: int) -> None:
    if port in PORTS_RESERVES:
        raise ValueError(f"Port {port} réservé à l'atelier.")
    _cible["port"] = port
    logger.info("Aperçu pointé sur le port {}", port)


def port_cible() -> int | None:
    return _cible["port"]


def ports_ecoutes() -> list[int]:
    """Ports TCP en écoute dans le conteneur, hors ceux de l'atelier lui-même."""
    ports: set[int] = set()
    for fichier in _TCP:
        try:
            lignes = fichier.read_text().splitlines()[1:]
        except OSError as exc:
            logger.warning("Lecture de {} impossible : {}", fichier, exc)
            continue
        for ligne in lignes:
            champs = ligne.split()
            if len(champs) > 3 and champs[3] == _LISTEN:
                adresse, port = champs[1].rsplit(":", 1)
                if adresse != _DNS_DOCKER:
                    ports.add(int(port, 16))
    return sorted(ports - PORTS_RESERVES)


def _entetes(source: httpx.Headers | dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in source.items() if k.lower() not in _SAUT_PAR_SAUT}


@app.api_route("/{chemin:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def relayer(chemin: str, requete: Request) -> Response:
    port = port_cible()
    if port is None:
        return Response("Aucun aperçu choisi : ouvrir l'app depuis la fenêtre du projet.", status_code=503)
    url = httpx.URL(f"http://127.0.0.1:{port}/{chemin}", query=requete.url.query.encode())
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            reponse = await client.request(requete.method, url, content=await requete.body(),
                                           headers=_entetes(dict(requete.headers)))
    except httpx.HTTPError as exc:
        logger.warning("Aperçu : port {} injoignable : {}", port, exc)
        return Response(f"Rien ne répond sur le port {port} de l'atelier.", status_code=502)
    return Response(reponse.content, status_code=reponse.status_code, headers=_entetes(reponse.headers))
