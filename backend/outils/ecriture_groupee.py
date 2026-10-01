"""Outil `ecrire_fichiers` — poser plusieurs fichiers indépendants en un seul appel.

Mesuré le 2026-10-01 (projet `spoofer`) : six fichiers écrits, cinq restants, et le modèle réécrit
sept fois « let me write them all in one batch » sans jamais y parvenir — `ecrire_fichier` ne
prend qu'un fichier, et il ne savait pas émettre cinq appels d'affilée. L'outil groupé lui donne
la forme qu'il réclamait. Chaque fichier passe par `ecrire_fichier` : même frontière de bac, même
dépôt dans le magasin, mêmes alias d'arguments.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from backend.outils.contrat import ContexteExecution, DescriptionOutil, EchecOutil, Outil
from backend.outils.fichiers_bac import DESCRIPTION_ECRIRE, OUTIL_ECRIRE

# Au-delà, l'appel lui-même devient trop long à émettre d'un bloc : mieux vaut deux appels.
FICHIERS_PAR_APPEL_MAX = 20

DESCRIPTION = DescriptionOutil(
    nom="ecrire_fichiers",
    description=(
        "Writes SEVERAL files in one call — the way to create the files of a new project or module "
        "that do not depend on each other's content. Each entry is a full file, content RAW. Same "
        f"rules as `ecrire_fichier`; up to {FICHIERS_PAR_APPEL_MAX} files per call. To change part of "
        "an existing file, use `modifier_fichier`."
    ),
    parametres={
        "type": "object",
        "properties": {
            "fichiers": {
                "type": "array",
                "description": "The files to write. Required, at least one.",
                "items": {
                    "type": "object",
                    "properties": {
                        "chemin": {"type": "string", "description": "Relative path, e.g. `src/app.py`."},
                        "contenu": {"type": "string", "description": "The full text of the file."},
                    },
                    "required": ["chemin", "contenu"],
                },
            },
        },
        "required": ["fichiers"],
    },
    alias={alias: "fichiers" for alias in ("files", "liste", "entries", "items")},
)


def _entrees(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """Liste des fichiers demandés. Une liste sérialisée en chaîne JSON est acceptée et décodée."""
    brut = DESCRIPTION.normaliser(arguments).get("fichiers")
    if isinstance(brut, str):
        try:
            brut = json.loads(brut)
        except json.JSONDecodeError as exc:
            raise EchecOutil(f"Échec : `fichiers` n'est pas une liste JSON lisible ({exc}).") from exc
    if not isinstance(brut, list) or not brut:
        raise EchecOutil(
            "Échec : `ecrire_fichiers` attend `fichiers`, une liste NON vide d'objets "
            "{\"chemin\": \"...\", \"contenu\": \"...\"}, tous dans le même appel."
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

__all__ = ["FICHIERS_PAR_APPEL_MAX", "OUTIL"]
