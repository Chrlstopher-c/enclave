"""Outil `plan_fichier` — la structure d'un fichier avant de le lire, pour n'en lire que la partie utile.

Le modèle relisait des fichiers ENTIERS (6 000 caractères chacun, tronqués) pour trouver une ligne, et
son contexte s'emplissait de ce qu'il n'utilisait pas (2026-10-02). Le plan rend les sections avec
leurs lignes de début et de fin : la lecture suivante se fait par plage (`lire_fichier` +
`ligne_debut`/`ligne_fin`). Marche sur le projet comme sur `~agent/` (AWARENESS.md, skills, mémoire).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from backend.outils.bac_a_sable import CheminHorsBac, resoudre_dans_bac
from backend.outils.contrat import ContexteExecution, DescriptionOutil, EchecOutil, Outil

SECTIONS_MAX = 150
TAILLE_MAX_OCTETS = 5_000_000

# Repères de structure par famille de fichiers : titres markdown, définitions de code.
_TITRE_MD = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_DEF_PY = re.compile(r"^(\s*)(?:async\s+)?(def|class)\s+(\w+)")
_DEF_TS = re.compile(
    r"^(\s*)(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(function\*?|class|interface|type|enum|const|let)\s+([A-Za-z_$][\w$]*)"
)
_SUFFIXES_TS = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"})
_SUFFIXES_MD = frozenset({".md", ".markdown", ".mdx", ".rst", ".txt"})

DESCRIPTION = DescriptionOutil(
    nom="plan_fichier",
    description=(
        "Shows the STRUCTURE of a file — markdown headings, or the classes and functions of a code file — "
        "each with its line range. Use it BEFORE reading a long file, then read only the section you need "
        "with `lire_fichier` + `ligne_debut`/`ligne_fin`. Works on project files and on `~agent/` files "
        "(e.g. `~agent/AWARENESS.md`)."
    ),
    parametres={
        "type": "object",
        "properties": {"chemin": {"type": "string", "description": "Relative path, or `~agent/…`."}},
        "required": ["chemin"],
    },
    alias={a: "chemin" for a in ("path", "fichier", "file", "file_path", "nom")},
)


def _reperes(lignes: list[str], suffixe: str) -> list[tuple[int, int, str]]:
    """(numéro de ligne 1-based, profondeur, libellé) des débuts de section."""
    reperes: list[tuple[int, int, str]] = []
    for numero, ligne in enumerate(lignes, 1):
        if suffixe in _SUFFIXES_MD or suffixe == "":
            if m := _TITRE_MD.match(ligne):
                reperes.append((numero, len(m.group(1)), m.group(2)))
            continue
        motif = _DEF_PY if suffixe == ".py" else _DEF_TS if suffixe in _SUFFIXES_TS else None
        if motif is not None and (m := motif.match(ligne)):
            reperes.append((numero, len(m.group(1)) // 2 + 1, f"{m.group(2)} {m.group(3)}"))
    return reperes


def plan(texte: str, suffixe: str) -> str:
    lignes = texte.splitlines()
    reperes = _reperes(lignes, suffixe)
    if not reperes:
        return (f"{len(lignes)} lines, no recognisable structure. Search it with `chercher_dans_fichiers`, "
                "or read it in ranges with `lire_fichier` + `ligne_debut`/`ligne_fin`.")
    sortie = [f"{len(lignes)} lines, {len(reperes)} section(s):"]
    for rang, (debut, profondeur, libelle) in enumerate(reperes[:SECTIONS_MAX]):
        fin = next((d - 1 for d, p, _ in reperes[rang + 1:] if p <= profondeur), len(lignes))
        sortie.append(f"{'  ' * (profondeur - 1)}- {libelle}  [lines {debut}-{fin}]")
    if len(reperes) > SECTIONS_MAX:
        sortie.append(f"[… {len(reperes) - SECTIONS_MAX} more sections]")
    return "\n".join(sortie)


async def _executer(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
    chemin = str(DESCRIPTION.normaliser(arguments).get("chemin", "")).strip()
    if not chemin:
        raise EchecOutil('Failed: `plan_fichier` needs `chemin`, e.g. {"chemin": "~agent/AWARENESS.md"}.')
    try:
        cible = resoudre_dans_bac(contexte.racine_bac, chemin)
    except CheminHorsBac as exc:
        raise EchecOutil(f"Échec : {exc}") from exc
    if not cible.is_file():
        raise EchecOutil(f"Échec : « {chemin} » n'existe pas.")
    try:
        if cible.stat().st_size > TAILLE_MAX_OCTETS:
            raise EchecOutil(f"Échec : « {chemin} » est trop gros pour un plan ; utiliser `chercher_dans_fichiers`.")
        texte = cible.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EchecOutil(f"Échec : « {chemin} » illisible en texte ({exc}).") from exc
    return f"Plan de « {chemin} » — {plan(texte, Path(chemin).suffix.lower())}"


OUTIL = Outil(description=DESCRIPTION, executer=_executer)

__all__ = ["OUTIL", "plan"]
