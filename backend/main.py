"""Point d'entrée de l'API — assemble les domaines.

Ce fichier est délibérément mince : il ne contient aucune logique métier. Chaque domaine
expose son routeur et son initialisation ; `main` ne fait que les monter et fixer le cycle
de vie de l'application.

Note d'assemblage : les domaines ont été écrits en parallèle et ne se sont pas accordés sur
le nom de leur routeur (`router` d'un côté, `routeur` de l'autre). On lit donc les deux
plutôt que de réécrire six domaines pour une question de nommage — la divergence est
absorbée ici, en un seul endroit.
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.requests import Request

from loguru import logger

from backend.core.config import get_settings
from backend.core.logging import setup_logging
from backend.core.errors import EchoHubError

setup_logging(get_settings())


def _routeur_du_module(chemin: str) -> APIRouter | None:
    """Récupère le routeur d'un domaine, quel que soit le nom qu'il lui a donné.

    Un domaine absent ou cassé ne doit pas empêcher les autres de démarrer : l'API sert
    alors ce qu'elle peut, et l'échec est journalisé plutôt que fatal.
    """
    import importlib

    try:
        module = importlib.import_module(chemin)
    except Exception as e:
        logger.error(f"domaine {chemin} non chargé ({type(e).__name__}: {e})")
        return None

    for nom in ("router", "routeur"):
        candidat = getattr(module, nom, None)
        if isinstance(candidat, APIRouter):
            return candidat
    logger.warning(f"domaine {chemin} chargé mais n'expose aucun routeur")
    return None


# Ordre d'assemblage : du plus fondamental au plus dépendant.
_DOMAINES = (
    "backend.system.api",
    "backend.models.api",
    "backend.engines.api",
    "backend.inference.api",
    "backend.chat.routes",
    "backend.fichiers.routes",
    "backend.outils.api",
    "backend.recherche.api",
    "backend.projets.routes",
)


def _preparer_persistance() -> None:
    """Crée le schéma commun, PUIS celui du chat — l'ordre est imposé par le domaine.

    `core.init_db()` porte les tables partagées, dont `modeles` : sans cet appel le registre
    répond « lecture en base échouée » sur une table qui n'a jamais existé, et l'écran Modèles
    reste vide sans que rien n'indique pourquoi.
    """
    from backend.chat import initialiser as initialiser_chat
    from backend.core.db import init_db

    init_db()
    initialiser_chat()


def _reprendre_transferts() -> None:
    """Un transfert coupé par un redémarrage doit repartir où il en était, pas disparaître."""
    from backend.models import gestionnaire

    repris = gestionnaire().reprendre_interrompus()
    if repris:
        logger.info(f"{len(repris)} téléchargement(s) interrompu(s) repris")


async def _arreter_moteur() -> None:
    """Arrête le moteur à l'extinction : sans cela, `llama-server` survivait à chaque reload du backend
    natif (re-parenté à systemd), gardait le port et la VRAM, et le backend suivant se croyait inactif."""
    try:
        from backend.inference import superviseur

        await superviseur.decharger()
    except Exception as e:  # noqa: BLE001 — l'arrêt doit aboutir même si le moteur résiste
        logger.error(f"arrêt du moteur à l'extinction impossible ({type(e).__name__}: {e})")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("EchoHub v2 — démarrage")
    # Chaque étape est isolée : une panne de reprise de transfert ne doit pas empêcher l'API de
    # servir, et l'échec est journalisé plutôt que silencieux.
    for etape in (_preparer_persistance, _reprendre_transferts):
        try:
            etape()
        except Exception as e:
            logger.error(f"{etape.__name__} a échoué ({type(e).__name__}: {e})")
    yield
    logger.info("EchoHub v2 — arrêt")
    await _arreter_moteur()


app = FastAPI(title="EchoHub", version="2.0.0", lifespan=lifespan)

# Le frontend est servi par nginx depuis la même origine et `/api` est réécrit avant d'arriver
# ici : en usage normal aucune requête n'est cross-origin. CORS reste ouvert en développement,
# où Vite sert le frontend sur un autre port.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(EchoHubError)
async def _erreur_domaine(_: Request, exc: EchoHubError) -> JSONResponse:
    """Les erreurs du domaine portent un message actionnable : on le rend tel quel plutôt
    que de le noyer dans une 500 générique."""
    logger.warning(f"{type(exc).__name__}: {exc}")
    return JSONResponse(status_code=getattr(exc, "code_http", 400), content={"detail": str(exc)})


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "2.0.0"}


for _chemin in _DOMAINES:
    _routeur = _routeur_du_module(_chemin)
    if _routeur is not None:
        app.include_router(_routeur)
        logger.info(f"domaine monté : {_chemin} ({_routeur.prefix or '/'})")
