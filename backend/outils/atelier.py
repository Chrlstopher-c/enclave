"""Client HTTP du conteneur atelier — la frontière réseau qui remplace le sous-processus confiné.

L'exécution du code et des commandes d'un modèle a quitté le backend : elle vit désormais dans un
conteneur de dev séparé (`echohub-atelier`), toujours actif, où l'agent est root et peut installer
des paquets. Le backend ne pilote PAS Docker — aucun `docker.sock` n'est monté, et c'est un choix
de sécurité : le socket Docker donne root sur l'hôte. Le backend parle à l'atelier par HTTP, sur le
réseau interne de la pile (le port de l'atelier n'est JAMAIS publié sur l'hôte), protégé par un
jeton partagé injecté en variable d'environnement.

Ce module est le SEUL endroit qui parle à l'atelier : un seul point à protéger par try/except, un
seul à journaliser, et un service testable en injectant un transport factice (`httpx.MockTransport`).
Le client est créé par appel, comme `recherche/client_searxng.py` — une exécution est un événement
ponctuel, mutualiser un client persistant imposerait un cycle de vie pour un gain nul.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx
from loguru import logger
from pydantic import BaseModel

from backend.core import get_settings

# Marge ajoutée au délai serveur pour obtenir le délai du client HTTP : l'atelier doit tuer une
# commande trop longue LUI-MÊME et rendre un résultat propre (`tue=True`), plutôt que de laisser le
# client expirer et perdre la sortie déjà produite. Le client attend donc toujours un peu plus.
MARGE_CLIENT_SECONDES = 30

_ENTETE_JETON = "X-Atelier-Jeton"

Racine = Literal["workspace", "projets"]
TIMEOUT_PROCESSUS_SECONDES = 20


class ReponseAtelier(BaseModel):
    """Ce que l'atelier a exécuté et renvoyé — jamais une exception, toujours ces champs."""

    code_retour: int
    sortie: str
    erreur: str
    duree_s: float
    tue: bool


class AtelierInjoignable(Exception):
    """L'atelier n'a pas répondu (arrêté, service down, jeton refusé). Message actionnable au modèle."""


def _message_repli(cause: str) -> str:
    """Texte rendu au modèle quand l'atelier ne répond pas : dit quoi faire, pas seulement quoi rater."""
    return (
        "L'atelier d'exécution n'est pas disponible "
        f"({cause}). Aucune commande ni aucun code n'a été exécuté. "
        "Démarrer l'atelier avec « docker compose up -d echohub-atelier » depuis la racine du "
        "projet, puis réessayer. Ne pas prétendre que la commande a abouti."
    )


def _poster(chemin: str, charge: dict[str, object], timeout_s: int) -> httpx.Response:
    reglages = get_settings()
    jeton = reglages.atelier_jeton.get_secret_value() if reglages.atelier_jeton else ""
    url = f"{reglages.atelier_url.rstrip('/')}{chemin}"
    return httpx.post(url, json=charge, headers={_ENTETE_JETON: jeton}, timeout=timeout_s + MARGE_CLIENT_SECONDES)


class RefusProcessus(Exception):
    """L'atelier a refusé une opération de processus (nom inconnu, borne atteinte). Message lisible."""


def piloter_processus(action: str, charge: dict[str, object]) -> dict[str, Any]:
    """Lancer / journal / arreter / lister un processus de fond. Lève `AtelierInjoignable` ou `RefusProcessus`."""
    try:
        reponse = _poster(f"/processus/{action}", charge, TIMEOUT_PROCESSUS_SECONDES)
    except httpx.HTTPError as exc:
        logger.error("Atelier injoignable (processus {}) : {}", action, exc)
        raise AtelierInjoignable(_message_repli("service non joignable")) from exc
    if reponse.status_code in (404, 409, 422):
        detail = reponse.json().get("detail", reponse.text) if reponse.content else reponse.reason_phrase
        raise RefusProcessus(str(detail))
    if reponse.status_code != 200:
        logger.error("Atelier a refusé processus/{} : {}", action, reponse.status_code)
        raise AtelierInjoignable(_message_repli(f"réponse {reponse.status_code}"))
    corps: dict[str, Any] = reponse.json()
    return corps


def _requete(chemin: str, charge: dict[str, object], timeout_s: int) -> ReponseAtelier:
    """Envoie une charge à l'atelier et rend sa réponse typée. Lève `AtelierInjoignable` sur échec.

    Le jeton part en en-tête, jamais dans le corps ni dans un journal. Une réponse non 200 est
    traitée comme un atelier injoignable : du point de vue de l'appelant, le service n'a pas fait
    le travail, la nuance HTTP ne l'aide pas.
    """
    try:
        reponse = _poster(chemin, charge, timeout_s)
        reponse.raise_for_status()
        return ReponseAtelier.model_validate(reponse.json())
    except httpx.HTTPStatusError as exc:
        logger.error("Atelier a refusé la requête ({}) : {}", chemin, exc.response.status_code)
        raise AtelierInjoignable(_message_repli(f"réponse {exc.response.status_code}")) from exc
    except httpx.HTTPError as exc:
        logger.error("Atelier injoignable ({}) : {}", chemin, exc)
        raise AtelierInjoignable(_message_repli("service non joignable sur le réseau interne")) from exc


def executer_commande(commande: str, sous_dossier: str, timeout_s: int,
                      racine: Racine = "workspace") -> ReponseAtelier:
    """Exécute une commande shell dans l'atelier, sous `<racine>/<sous_dossier>`. Peut lever."""
    return _requete("/executer/commande",
                    {"commande": commande, "sous_dossier": sous_dossier, "timeout_s": timeout_s,
                     "racine": racine},
                    timeout_s)


def executer_python(code: str, sous_dossier: str, timeout_s: int,
                    racine: Racine = "workspace") -> ReponseAtelier:
    """Exécute du code Python dans l'atelier, sous `<racine>/<sous_dossier>`. Peut lever."""
    return _requete("/executer/python",
                    {"code": code, "sous_dossier": sous_dossier, "timeout_s": timeout_s,
                     "racine": racine},
                    timeout_s)


__all__ = ["ReponseAtelier", "AtelierInjoignable", "RefusProcessus", "Racine", "executer_commande",
           "executer_python", "piloter_processus"]
