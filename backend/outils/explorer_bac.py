"""Outils `lister_fichiers` et `chercher_dans_fichiers` — voir le bac au lieu de s'en souvenir.

Jusqu'ici le modèle n'avait aucun moyen de savoir ce que contenait son bac : il écrivait, puis il
se fiait à sa mémoire de ce qu'il avait écrit. Le socle dit pourtant l'inverse en toutes lettres —
« Your memory of what you wrote is not the file » — sans donner l'outil qui permettrait d'y obéir.

Le trou s'est élargi avec `executer_commande` : une compilation, un `git clone`, une extraction
d'archive produisent des fichiers que le modèle n'a pas nommés lui-même. Sans listage, il ne peut
ni les citer, ni les lire, ni les présenter à l'utilisateur.

POURQUOI DES OUTILS DÉDIÉS PLUTÔT QUE `ls` ET `grep` PAR `executer_commande` : la sortie d'un outil
est normalisée et bornée, là où celle d'une commande dépend de l'implémentation présente dans
l'image et de la façon dont le modèle a écrit ses options. Un `find` mal écrit rend une erreur que
le modèle doit interpréter ; un listage dédié rend toujours la même forme. Le shell reste la bonne
route pour tout le reste — c'est ce que disent les descriptions.
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from loguru import logger

from backend.agent import PREFIXE as PREFIXE_MAISON
from backend.agent import racine as racine_maison
from backend.outils.bac_a_sable import CheminHorsBac, est_maison, preparer_bac, resoudre_dans_bac
from backend.outils.contrat import ContexteExecution, DescriptionOutil, EchecOutil, Outil

# Bornes de sortie. Un bac contenant un dépôt cloné dépasse vite le millier de fichiers, et lister
# le tout mangerait le contexte pour rien : la troncature est ANNONCÉE, jamais silencieuse, sinon
# le modèle conclut à l'absence d'un fichier simplement coupé de la liste.
FICHIERS_MAX = 200
CORRESPONDANCES_MAX = 60
LONGUEUR_LIGNE_MAX = 200
# Un fichier binaire n'a pas de lignes à montrer, et sa lecture en texte produit du bruit.
TAILLE_FICHIER_MAX_OCTETS = 2_000_000

_SCHEMA_LISTE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "motif": {
            "type": "string",
            "description": (
                "Optional glob pattern to filter, relative to the sandbox — `*.py`, `src/**/*.c`. "
                "Omit it to list everything. Not a regular expression."
            ),
        },
    },
}

DESCRIPTION_LISTE = DescriptionOutil(
    nom="lister_fichiers",
    description=(
        "Lists the files really present in this conversation's sandbox, with their size. Call it "
        "before assuming a file exists, after a command that may have produced files (compiling, "
        "cloning, extracting), and whenever you are about to name a file you did not write "
        "yourself in this turn. Optional `motif` filters with a glob pattern."
    ),
    parametres=_SCHEMA_LISTE,
    alias={a: "motif" for a in ("pattern", "filtre", "glob", "masque", "extension")},
)

_SCHEMA_RECHERCHE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "texte": {
            "type": "string",
            "description": (
                "Literal text to look for. Required — matching is plain text, not a regular "
                "expression, and it ignores case."
            ),
        },
        "motif": {
            "type": "string",
            "description": "Optional glob pattern restricting which files are searched — `*.py`.",
        },
    },
    "required": ["texte"],
}

DESCRIPTION_RECHERCHE = DescriptionOutil(
    nom="chercher_dans_fichiers",
    description=(
        "Searches for a literal text across the files of this conversation's sandbox and returns "
        "each match with its file and line number. Use it to locate a function, a constant or an "
        "error message inside a project you did not write in full — reading whole files to find "
        "one line wastes the context you need for the answer."
    ),
    parametres=_SCHEMA_RECHERCHE,
    alias={
        **{a: "texte" for a in ("query", "recherche", "terme", "chaine", "pattern", "text")},
        **{a: "motif" for a in ("filtre", "glob", "fichiers", "masque")},
    },
)


# Dossiers de dépendances et de build : jamais parcourus. Dans un projet, `node_modules` seul pèse
# des dizaines de milliers de fichiers — les lister noierait le modèle et gèlerait l'outil.
DOSSIERS_IGNORES = frozenset({"node_modules", "__pycache__", "venv", "dist", "build", "target", "coverage"})


def _parcourir(racine: Path) -> Iterator[Path]:
    """Fichiers sous `racine`, en élaguant dossiers cachés et dossiers de dépendances SANS y descendre."""
    for dossier, sous_dossiers, fichiers in os.walk(racine):
        sous_dossiers[:] = [d for d in sous_dossiers if not d.startswith(".") and d not in DOSSIERS_IGNORES]
        for nom in fichiers:
            if not nom.startswith("."):
                yield Path(dossier) / nom


def _fichiers(racine: Path, motif: str) -> list[Path]:
    """Fichiers du bac correspondant au motif, triés, hors dossiers cachés et de dépendances."""
    try:
        motif_effectif = motif or "*"
        retenus = [c for c in _parcourir(racine)
                   if c.relative_to(racine).match(motif_effectif) or fnmatch.fnmatch(c.name, motif_effectif)]
    except (OSError, ValueError) as exc:
        raise EchecOutil(f"Pattern « {motif} » cannot be used: {exc}") from exc
    return sorted(retenus)


def _lister(racine: Path, motif: str, prefixe: str = "") -> str:
    fichiers = _fichiers(racine, motif)
    if not fichiers:
        precision = f" matching « {motif} »" if motif else ""
        return (f"The sandbox contains no file{precision}. "
                "Nothing has been written here yet, or the pattern matches nothing.")
    lignes = [f"{len(fichiers)} fichier(s) dans le bac :"]
    for chemin in fichiers[:FICHIERS_MAX]:
        try:
            taille = chemin.stat().st_size
        except OSError:
            taille = -1
        relatif = f"{prefixe}{chemin.relative_to(racine).as_posix()}"
        lignes.append(f"  {relatif}  ({taille} octets)" if taille >= 0 else f"  {relatif}  (illisible)")
    if len(fichiers) > FICHIERS_MAX:
        lignes.append(f"  [liste tronquée : {len(fichiers) - FICHIERS_MAX} fichier(s) de plus, "
                      f"affiner avec `motif`]")
    return "\n".join(lignes)


def _lignes_correspondantes(chemin: Path, aiguille: str) -> list[tuple[int, str]]:
    """Lignes d'un fichier contenant l'aiguille. Un fichier illisible est sauté, jamais fatal."""
    try:
        if chemin.stat().st_size > TAILLE_FICHIER_MAX_OCTETS:
            return []
        contenu = chemin.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        return []
    return [(numero, ligne) for numero, ligne in enumerate(contenu.splitlines(), 1)
            if aiguille in ligne.lower()]


def _chercher(racine: Path, texte: str, motif: str, prefixe: str = "") -> str:
    aiguille = texte.lower()
    lignes: list[str] = []
    total = 0
    for chemin in _fichiers(racine, motif):
        for numero, ligne in _lignes_correspondantes(chemin, aiguille):
            total += 1
            if len(lignes) < CORRESPONDANCES_MAX:
                extrait = ligne.strip()[:LONGUEUR_LIGNE_MAX]
                lignes.append(f"  {prefixe}{chemin.relative_to(racine).as_posix()}:{numero}: {extrait}")
    if not total:
        return (f"« {texte} » appears in no file of the sandbox. "
                "Check the spelling, or list the files first with `lister_fichiers`.")
    entete = f"{total} correspondance(s) pour « {texte} » :"
    if total > CORRESPONDANCES_MAX:
        lignes.append(f"  [tronqué : {total - CORRESPONDANCES_MAX} correspondance(s) de plus]")
    return "\n".join([entete, *lignes])


def _cible(contexte: ContexteExecution, motif: str) -> tuple[Path, str, str]:
    """(racine à parcourir, motif relatif à elle, préfixe d'affichage) — la maison si `~agent/`."""
    if est_maison(motif or ""):
        reste = motif.strip()[len(PREFIXE_MAISON):] if motif.strip() != "~agent" else ""
        try:
            resoudre_dans_bac(contexte.racine_bac, PREFIXE_MAISON + reste.replace("*", "x").replace("?", "x"))
        except CheminHorsBac as exc:
            raise EchecOutil(f"Pattern refused: {exc}") from exc
        return racine_maison(), reste, PREFIXE_MAISON
    return _racine_verifiee(contexte, motif), motif, ""


def _racine_verifiee(contexte: ContexteExecution, motif: str) -> Path:
    """Racine du bac, après avoir refusé un motif qui tenterait d'en sortir."""
    preparer_bac(contexte.racine_bac)
    if motif:
        # Le motif est une entrée non fiable au même titre qu'un chemin : `../../etc/*` sortirait
        # du bac par `rglob` sans que rien ne le signale. On le résout comme un chemin, ce qui
        # rejette l'absolu et la remontée, avant de s'en servir comme filtre.
        try:
            resoudre_dans_bac(contexte.racine_bac, motif.replace("*", "x").replace("?", "x"))
        except CheminHorsBac as exc:
            raise EchecOutil(f"Pattern refused: {exc} Use a pattern relative to the sandbox.") from exc
    return contexte.racine_bac.resolve()


async def executer_liste(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
    """Liste les fichiers du bac de `contexte`."""
    racine, motif, prefixe = _cible(contexte, str(arguments.get("motif", "")).strip())
    resultat = await asyncio.to_thread(_lister, racine, motif, prefixe)
    logger.info("lister_fichiers : motif={} → {} caractères", motif or "*", len(resultat))
    return resultat


async def executer_recherche(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
    """Cherche un texte littéral dans les fichiers du bac de `contexte`."""
    texte = str(arguments.get("texte", "")).strip()
    if not texte:
        raise EchecOutil(
            "No text to search for. Send the `texte` argument, "
            'for example: {"texte": "def main"}')
    racine, motif, prefixe = _cible(contexte, str(arguments.get("motif", "")).strip())
    resultat = await asyncio.to_thread(_chercher, racine, texte, motif, prefixe)
    logger.info("chercher_dans_fichiers : « {} » motif={} → {} caractères", texte, motif or "*", len(resultat))
    return resultat


OUTIL_LISTER = Outil(description=DESCRIPTION_LISTE, executer=executer_liste)
OUTIL_CHERCHER = Outil(description=DESCRIPTION_RECHERCHE, executer=executer_recherche)

__all__ = ["OUTIL_CHERCHER", "OUTIL_LISTER"]
