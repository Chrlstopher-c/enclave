"""Outil `ecrire_fichiers` — poser plusieurs fichiers indépendants en un seul appel.

Mesuré le 2026-10-01 (projet `spoofer`) : six fichiers écrits, cinq restants, et le modèle réécrit
sept fois « let me write them all in one batch » sans jamais y parvenir — `ecrire_fichier` ne
prend qu'un fichier, et il ne savait pas émettre cinq appels d'affilée. L'outil groupé lui donne
la forme qu'il réclamait. Chaque fichier passe par `ecrire_fichier` : même frontière de bac, même
dépôt dans le magasin, mêmes alias d'arguments.
"""

from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

from backend.outils.contrat import ContexteExecution, DescriptionOutil, EchecOutil, Outil
from backend.outils.fichiers_bac import DESCRIPTION_ECRIRE, OUTIL_ECRIRE

# Au-delà, l'appel lui-même devient trop long à émettre d'un bloc : mieux vaut deux appels.
FICHIERS_PAR_APPEL_MAX = 20

# Format TEXTE BRUT des fichiers groupés. Constaté le 2026-11-11 (MoE 35B, appels XML) : une LISTE d'objets oblige le
# modèle à écrire du code en JSON à l'intérieur du XML, donc à échapper chaque `"`. Un `"""` mal échappé fermait la
# chaîne trop tôt : guillemets perdus, fichier tronqué, trois fichiers à réécrire. En texte brut, rien à échapper —
# comme `ecrire_fichier`, qui n'a jamais eu ce défaut.
ENTETE = re.compile(r"^=== FILE: (?P<chemin>[^\n]*?\S) ===[ \t]*$", re.MULTILINE)

DESCRIPTION = DescriptionOutil(
    nom="ecrire_fichiers",
    description=(
        "Writes SEVERAL files in one call — the way to create the files of a new project or module that do not "
        "depend on each other's content. Put all the files in the single argument, as PLAIN TEXT, each one introduced by a "
        "header line `=== FILE: <relative path> ===` followed by its full raw content (no quoting, no escaping):\n"
        "=== FILE: app/__init__.py ===\n\"\"\"Package.\"\"\"\n=== FILE: app/config.py ===\nPORT = 8000\n"
        f"Up to {FICHIERS_PAR_APPEL_MAX} files per call; a very large file gets its own `ecrire_fichier` call. To "
        "change part of an existing file, use `modifier_fichier`."
    ),
    parametres={
        "type": "object",
        "properties": {
            "fichiers": {
                "type": "string",
                "description": "All the files, each starting with its header line `=== FILE: <path> ===`, then "
                               "its raw content.",
            },
        },
        "required": ["fichiers"],
    },
    alias={alias: "fichiers" for alias in ("files", "liste", "entries", "items")},
)


def sections(texte: str) -> list[dict[str, str]]:
    """Fichiers du format texte, dans l'ordre : `{chemin, contenu}`, le contenu tel qu'écrit (sans la ligne d'en-tête)."""
    entetes = list(ENTETE.finditer(texte))
    fichiers = []
    for rang, entete in enumerate(entetes):
        fin = entetes[rang + 1].start() if rang + 1 < len(entetes) else len(texte)
        contenu = texte[entete.end():fin].removeprefix("\n")
        fichiers.append({"chemin": entete.group("chemin").strip(), "contenu": contenu})
    return fichiers


def _entrees(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """Fichiers demandés : format texte (`=== FILE: … ===`), ou liste JSON d'objets {chemin, contenu}."""
    brut = DESCRIPTION.normaliser(arguments).get("fichiers")
    if isinstance(brut, str) and ENTETE.search(brut):
        brut = sections(brut)
    elif isinstance(brut, str):
        try:
            brut = json.loads(brut)
        except json.JSONDecodeError as exc:
            raise EchecOutil(
                "Échec : `fichiers` ne contient aucune ligne d'en-tête `=== FILE: <chemin> ===`. Écrire chaque "
                f"fichier précédé de sa ligne d'en-tête, contenu brut ensuite ({exc}).") from exc
    if not isinstance(brut, list) or not brut:
        raise EchecOutil(
            "Échec : `ecrire_fichiers` attend `fichiers` : chaque fichier précédé d'une ligne "
            "`=== FILE: <chemin> ===`, puis son contenu brut."
        )
    if len(brut) > FICHIERS_PAR_APPEL_MAX:
        raise EchecOutil(f"Échec : {len(brut)} fichiers demandés, {FICHIERS_PAR_APPEL_MAX} au plus par appel. "
                         "Répartir sur deux appels.")
    return [DESCRIPTION_ECRIRE.normaliser(e) if isinstance(e, dict) else {} for e in brut]


async def _executer(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
    ecrits: list[str] = []
    echecs: list[str] = []
    for rang, entree in enumerate(_entrees(arguments), start=1):
        try:
            ecrits.append(await OUTIL_ECRIRE.executer(entree, contexte))
        except EchecOutil as exc:
            nom = str(entree.get("chemin") or f"entrée {rang}")
            echecs.append(f"- {nom} : {exc}")
    if echecs:
        logger.warning("ecrire_fichiers : {} écrit(s), {} refusé(s).", len(ecrits), len(echecs))
        faits = "\n".join(ecrits) or "aucun"
        raise EchecOutil(f"Écrits :\n{faits}\nRefusés (à renvoyer corrigés) :\n" + "\n".join(echecs))
    return f"{len(ecrits)} fichier(s) écrit(s) :\n" + "\n".join(ecrits)


OUTIL = Outil(description=DESCRIPTION, executer=_executer)

__all__ = ["ENTETE", "FICHIERS_PAR_APPEL_MAX", "OUTIL", "sections"]
