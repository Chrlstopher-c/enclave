"""Normes de taille : fichier ≤ 500 lignes, fonction ≤ 35, ligne ≤ 120 caractères."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from rapport import Rapport

MAX_FICHIER, MAX_FONCTION, MAX_LIGNE = 500, 35, 120
_FONCTION_JS = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\s*\*?\s*(\w+)\s*\("
    r"|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>"
    r"|(?:(?:public|private|protected|static|async)\s+)*(\w+)\s*\([^)]*\)\s*(?::[^{]+)?\{)")
_MOTS_CLES = {"if", "for", "while", "switch", "catch", "return", "function"}


def fonctions_python(texte: str) -> list[tuple[str, int, int]]:
    """(nom, ligne, longueur) de chaque fonction ou méthode."""
    arbre = ast.parse(texte)
    return [(n.name, n.lineno, (n.end_lineno or n.lineno) - n.lineno + 1) for n in ast.walk(arbre)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def fonctions_js(lignes: list[str]) -> list[tuple[str, int, int]]:
    """Approximation par accolades : suffisante pour repérer une fonction trop longue."""
    trouvees = []
    for i, ligne in enumerate(lignes):
        m = _FONCTION_JS.match(ligne)
        nom = m and next((g for g in m.groups() if g), None)
        if not nom or nom in _MOTS_CLES or "{" not in "".join(lignes[i:i + 3]):
            continue
        profondeur, vu = 0, False
        for j in range(i, len(lignes)):
            profondeur += lignes[j].count("{") - lignes[j].count("}")
            vu = vu or "{" in lignes[j]
            if vu and profondeur <= 0:
                trouvees.append((nom, i + 1, j - i + 1))
                break
    return trouvees


def verifier(fichier: Path, texte: str, rapport: Rapport) -> None:
    lignes = texte.splitlines()
    defauts = []
    if len(lignes) > MAX_FICHIER:
        defauts.append(f"file has {len(lignes)} lines (max {MAX_FICHIER}): split it by responsibility")
    if fichier.suffix == ".py":
        try:
            fonctions = fonctions_python(texte)
        except SyntaxError:
            fonctions = []
    elif fichier.suffix in {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"}:
        fonctions = fonctions_js(lignes)
    else:
        fonctions = []
    defauts += [f"l.{l} {nom}() is {n} lines (max {MAX_FONCTION}): extract parts"
                for nom, l, n in fonctions if n > MAX_FONCTION]
    longues = [i + 1 for i, l in enumerate(lignes) if len(l) > MAX_LIGNE]
    if longues and fichier.suffix not in {".json", ".html", ".css"}:
        defauts.append(f"{len(longues)} line(s) over {MAX_LIGNE} chars: l.{', l.'.join(map(str, longues[:8]))}")
    if defauts:
        rapport.echec("size rules", defauts)
    else:
        rapport.ok(f"size rules ({len(lignes)} lines, {len(fonctions)} functions)")
