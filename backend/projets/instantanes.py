"""Instantanés d'un projet — un dépôt git SÉPARÉ, pris avant chaque tour du modèle, pour tout annuler.

Le dépôt vit dans `<projet>/.echohub/instantanes.git` avec le projet comme arbre de travail : le `.git`
propre au projet n'est jamais touché (git ignore toujours les dossiers `.git`), l'historique de
l'utilisateur reste le sien. Les dossiers de dépendances et de build sont exclus : on sauvegarde ce
que le modèle ÉCRIT, pas ce qu'un `bun install` régénère.

Exécuté dans l'atelier (qui porte git), par le harnais et non par le modèle : les garde-fous ne
s'appliquent pas ici, et `.echohub` reste inaccessible au modèle.
"""

from __future__ import annotations

import re
import shlex

from loguru import logger

from backend.outils.atelier import AtelierInjoignable, executer_commande
from backend.projets.modeles import Instantane
from backend.projets.racine import ProjetInvalide, chemin_projet

TIMEOUT_SECONDES = 120
HISTORIQUE_MAX = 50
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_EXCLUSIONS = ("/.echohub/", "node_modules/", ".venv/", "venv/", "__pycache__/", "*.pyc", "dist/", "build/",
               ".next/", "target/", ".cache/", "coverage/")
_GIT = ("git -c safe.directory='*' -c user.name=EchoHub -c user.email=echohub@localhost "
        "--git-dir=.echohub/instantanes.git --work-tree=.")
_INIT = (
    "[ -d .echohub/instantanes.git ] || { mkdir -p .echohub && printf '*\\n' > .echohub/.gitignore && "
    f"git init -q --bare .echohub/instantanes.git && printf '%s\\n' {' '.join(shlex.quote(e) for e in _EXCLUSIONS)} "
    "> .echohub/instantanes.git/info/exclude; }"
)


class InstantaneImpossible(ProjetInvalide):
    code = "instantane_impossible"
    statut_http = 502


def _lancer(nom: str, script: str) -> str:
    chemin_projet(nom)
    try:
        reponse = executer_commande(f"set -e; {_INIT}; {script}", nom, TIMEOUT_SECONDES, "projets")
    except AtelierInjoignable as exc:
        raise InstantaneImpossible(str(exc)) from exc
    if reponse.code_retour != 0:
        logger.error("Instantané de {} en échec : {}", nom, reponse.erreur[-500:])
        raise InstantaneImpossible(f"git a échoué : {reponse.erreur.strip()[-300:]}")
    return reponse.sortie


def prendre(nom: str, message: str) -> str | None:
    """Commit de l'état courant s'il a changé. Rend le sha, ou `None` si rien n'a changé."""
    script = (f"{_GIT} add -A; if {_GIT} rev-parse -q --verify HEAD >/dev/null && {_GIT} diff --cached --quiet; "
              f"then echo AUCUN; else {_GIT} commit -q --allow-empty -m {shlex.quote(message[:200])} && "
              f"{_GIT} rev-parse HEAD; fi")
    sortie = _lancer(nom, script).strip()
    return None if sortie.endswith("AUCUN") or not sortie else sortie.splitlines()[-1]


def prendre_sans_echec(nom: str, message: str) -> None:
    """Variante du harnais avant un tour : un instantané raté se journalise, il ne bloque pas le modèle."""
    try:
        sha = prendre(nom, message)
        logger.info("Instantané de « {} » : {}", nom, sha or "inchangé")
    except ProjetInvalide as exc:
        logger.warning("Instantané de « {} » impossible : {}", nom, exc)


def lister(nom: str) -> list[Instantane]:
    sortie = _lancer(nom, f"{_GIT} log --format='%H%x09%ct%x09%s' -n {HISTORIQUE_MAX} 2>/dev/null || true")
    resultat: list[Instantane] = []
    for ligne in sortie.splitlines():
        morceaux = ligne.split("\t", 2)
        if len(morceaux) == 3 and _SHA.match(morceaux[0]):
            resultat.append(Instantane(sha=morceaux[0], date=float(morceaux[1]), message=morceaux[2]))
    return resultat


def restaurer(nom: str, sha: str) -> str | None:
    """Ramène l'arbre du projet à `sha`, après un instantané de l'état courant (la restauration s'annule)."""
    if not _SHA.match(sha):
        raise ProjetInvalide(f"Identifiant d'instantané invalide : « {sha} ».")
    filet = prendre(nom, f"avant restauration de {sha[:8]}")
    _lancer(nom, f"{_GIT} cat-file -e {sha}^{{commit}} && {_GIT} read-tree -u --reset {sha}")
    logger.info("Projet « {} » restauré à {}", nom, sha[:8])
    return filet
