"""Aperçu de l'app d'un projet : pointer le relais de l'atelier sur le port de son serveur de dev.

L'app est servie par le relais (`atelier/apercu.py`), à la racine d'un port publié sur l'hôte ; le
backend ne relaie aucun octet, il dit seulement au relais quel port servir et rend l'URL à ouvrir.
Un seul aperçu à la fois pour tout l'atelier : le dernier pointé gagne.
"""

from __future__ import annotations

from loguru import logger

from backend.core import get_settings
from backend.core.errors import EchoHubError
from backend.outils.atelier import AtelierInjoignable, RefusProcessus, piloter_apercu
from backend.projets.modeles import EtatApercu
from backend.projets.racine import chemin_projet


class ApercuIndisponible(EchoHubError):
    """L'atelier n'a pas pu lire ou pointer le relais d'aperçu."""

    code = "apercu_indisponible"
    statut_http = 502
    remediation_defaut = "Vérifier que l'atelier tourne (start.sh) et que le serveur de l'app est lancé."


class ApercuRefuse(EchoHubError):
    """Le relais a refusé le port demandé (réservé à l'atelier)."""

    code = "apercu_refuse"
    statut_http = 409


def _etat(reponse: dict[str, object]) -> EtatApercu:
    port = reponse.get("port")
    ports = reponse.get("ports", [])
    url = get_settings().atelier_apercu_url.rstrip("/") + "/"
    return EtatApercu(port=port if isinstance(port, int) else None,
                      ports=[p for p in ports if isinstance(p, int)] if isinstance(ports, list) else [],
                      url=url)


def lire(nom: str) -> EtatApercu:
    chemin_projet(nom)
    try:
        return _etat(piloter_apercu())
    except (AtelierInjoignable, RefusProcessus) as exc:
        raise ApercuIndisponible(str(exc)) from exc


def pointer(nom: str, port: int) -> EtatApercu:
    chemin_projet(nom)
    try:
        etat = _etat(piloter_apercu(port))
    except RefusProcessus as exc:
        raise ApercuRefuse(str(exc)) from exc
    except AtelierInjoignable as exc:
        raise ApercuIndisponible(str(exc)) from exc
    logger.info("Aperçu du projet « {} » : port {}", nom, port)
    return etat


__all__ = ["ApercuIndisponible", "ApercuRefuse", "lire", "pointer"]
