"""Racine des projets : lister, créer, résoudre un projet — jamais un chemin hors de la racine.

La racine (`ECHOHUB_PROJETS_RACINE`) est un dossier de l'hôte choisi par l'utilisateur, monté aussi
dans l'atelier sous `/projets`. Un projet est un sous-dossier DIRECT, au nom contraint (minuscules,
chiffres, `.-_`) : pas de chemin imbriqué, pas de `..`, pas de lien symbolique qui ressortirait.
"""

from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

from backend.core import get_settings
from backend.core.errors import EchoHubError
from backend.projets.modeles import MOTIF_NOM, CatalogueProjets, Projet

DOSSIER_INSTANTANES = ".echohub"


class ProjetsDesactives(EchoHubError):
    code = "projets_desactives"
    statut_http = 503
    remediation_defaut = "Définir ECHOHUB_PROJETS_RACINE (dossier de l'hôte) puis redémarrer le backend."


class ProjetInvalide(EchoHubError):
    code = "projet_invalide"
    statut_http = 404


def racine() -> Path:
    """Racine configurée et existante, ou lève `ProjetsDesactives`."""
    configuree = get_settings().projets_racine
    if configuree is None:
        raise ProjetsDesactives("Le mode projet n'est pas configuré sur cette installation.")
    try:
        configuree.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("Racine des projets inaccessible ({}) : {}", configuree, exc)
        raise ProjetsDesactives(f"Racine des projets inaccessible : {exc}") from exc
    return configuree.resolve()


def chemin_projet(nom: str) -> Path:
    """Dossier du projet `nom`, existant et réellement sous la racine. Lève `ProjetInvalide` sinon."""
    if not re.match(MOTIF_NOM, nom or ""):
        raise ProjetInvalide(f"Nom de projet invalide : « {nom} ».")
    base = racine()
    cible = (base / nom).resolve()
    if cible.parent != base or not cible.is_dir():
        raise ProjetInvalide(f"Projet introuvable : « {nom} ».")
    return cible


def _decrire(dossier: Path) -> Projet:
    return Projet(nom=dossier.name, modifie_le=dossier.stat().st_mtime,
                  instantanes=(dossier / DOSSIER_INSTANTANES).is_dir())


def catalogue() -> CatalogueProjets:
    """Projets de la racine, plus récents d'abord. Racine absente = catalogue inactif, pas une erreur."""
    try:
        base = racine()
    except ProjetsDesactives:
        return CatalogueProjets(actif=False)
    try:
        dossiers = [d for d in base.iterdir() if d.is_dir() and re.match(MOTIF_NOM, d.name)]
        projets = sorted((_decrire(d) for d in dossiers), key=lambda p: p.modifie_le, reverse=True)
    except OSError as exc:
        logger.error("Lecture de la racine des projets impossible : {}", exc)
        raise ProjetsDesactives(f"Lecture de la racine impossible : {exc}") from exc
    return CatalogueProjets(actif=True, racine=str(base), projets=projets)


def creer(nom: str) -> Projet:
    """Crée le dossier du projet. Un projet existant est rendu tel quel : créer est idempotent."""
    if not re.match(MOTIF_NOM, nom or ""):
        raise ProjetInvalide(f"Nom de projet invalide : « {nom} ».")
    cible = racine() / nom
    try:
        cible.mkdir(exist_ok=True)
    except OSError as exc:
        logger.error("Création du projet {} impossible : {}", nom, exc)
        raise ProjetInvalide(f"Création impossible : {exc}") from exc
    logger.info("Projet « {} » prêt dans {}", nom, cible)
    return _decrire(cible)
