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
from backend.projets.modeles import DiffFichier, Instantane, Modification, ModificationsProjet
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


DIFF_MAX_OCTETS = 200_000
_SANS_INSTANTANE = "SANS_INSTANTANE"
_COUPURE = "---ECHOHUB---"


def modifications(nom: str) -> ModificationsProjet:
    """Fichiers changés depuis le dernier instantané, avec leurs lignes ajoutées et retirées.

    `add -A` ne touche que l'index du dépôt d'instantanés, que le prochain `prendre` refait de toute
    façon : c'est ce qui fait apparaître les fichiers NOUVEAUX, qu'un simple `diff HEAD` ignore.
    """
    script = (f"{_GIT} add -A; if ! {_GIT} rev-parse -q --verify HEAD >/dev/null; then echo {_SANS_INSTANTANE}; "
              f"else {_GIT} log -1 --format='%H%x09%ct%x09%s'; echo {_COUPURE}; "
              f"{_GIT} diff --cached --no-renames --name-status HEAD; echo {_COUPURE}; "
              f"{_GIT} diff --cached --no-renames --numstat HEAD; fi")
    sortie = _lancer(nom, script)
    if _SANS_INSTANTANE in sortie:
        return ModificationsProjet(reference=None)
    entete, etats, chiffres = (sortie.split(_COUPURE) + ["", ""])[:3]
    sha, date, message = (entete.strip().split("\t", 2) + ["", "0", ""])[:3]
    reference = Instantane(sha=sha, date=float(date or 0), message=message) if _SHA.match(sha) else None
    return ModificationsProjet(reference=reference, fichiers=_fusionner(etats, chiffres))


def _fusionner(etats: str, chiffres: str) -> list[Modification]:
    comptes: dict[str, tuple[int | None, int | None]] = {}
    for ligne in chiffres.strip().splitlines():
        morceaux = ligne.split("\t", 2)
        if len(morceaux) == 3:
            ajouts, retraits, chemin = morceaux
            comptes[chemin] = (int(ajouts) if ajouts.isdigit() else None,
                               int(retraits) if retraits.isdigit() else None)
    resultat: list[Modification] = []
    for ligne in etats.strip().splitlines():
        morceaux = ligne.split("\t", 1)
        if len(morceaux) == 2:
            ajouts, retraits = comptes.get(morceaux[1], (None, None))
            resultat.append(Modification(chemin=morceaux[1], etat=morceaux[0][:1], ajouts=ajouts,
                                         suppressions=retraits))
    return resultat


def diff(nom: str, chemin: str) -> DiffFichier:
    """Diff unifié d'un fichier depuis le dernier instantané (vide sans instantané de référence)."""
    if not chemin or chemin.startswith("-") or ".echohub" in chemin.split("/"):
        raise ProjetInvalide(f"Chemin refusé : « {chemin} ».")
    script = (f"{_GIT} add -A; {_GIT} rev-parse -q --verify HEAD >/dev/null || exit 0; "
              f"{_GIT} diff --cached --no-renames HEAD -- {shlex.quote(chemin)} | head -c {DIFF_MAX_OCTETS + 1}")
    sortie = _lancer(nom, script)
    return DiffFichier(chemin=chemin, diff=sortie[:DIFF_MAX_OCTETS], tronque=len(sortie) > DIFF_MAX_OCTETS)
