"""Le fichier est-il branché au projet (importé, chargé, lancé) et ses fonctions servent-elles ?"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from projet import chercher, relatif
from rapport import Rapport

_IMPORT = re.compile(r"\bimport\b|\bfrom\b|require\(|src=|href=|@import|<script|include|source\s")
_TEST = re.compile(r"(^|/)(tests?/|test_[^/]*$|[^/]*_test\.py$|[^/]*\.(test|spec)\.[jt]sx?$)")
_ENTREES = {"main", "app", "index", "server", "cli", "manage", "__main__", "conftest", "setup", "vite.config"}
_EXPORT_JS = re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?(?:function|const|class|let)\s+(\w+)", re.M)


def est_test(chemin: Path, base: Path) -> bool:
    return bool(_TEST.search(relatif(chemin, base)))


def _point_d_entree(fichier: Path, texte: str, base: Path) -> str | None:
    if fichier.stem in _ENTREES or fichier.name in {"__init__.py"} or est_test(fichier, base):
        return "entry point / package / test"
    if "__name__ == \"__main__\"" in texte or "__name__ == '__main__'" in texte or texte.startswith("#!"):
        return "runnable script"
    for manifeste in ("package.json", "pyproject.toml", "start.sh", "Makefile", "Dockerfile"):
        chemin = base / manifeste
        if chemin.exists() and relatif(fichier, base) in chemin.read_text(errors="ignore"):
            return f"referenced by {manifeste}"
    return None


def _symboles(fichier: Path, texte: str) -> list[tuple[str, int]]:
    if fichier.suffix == ".py":
        try:
            arbre = ast.parse(texte)
        except SyntaxError:
            return []
        # Décorées = branchées par un framework (route, fixture, commande) : jamais « inutilisées ».
        return [(n.name, n.lineno) for n in arbre.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not n.decorator_list]
    return [(m.group(1), texte[:m.start()].count("\n") + 1) for m in _EXPORT_JS.finditer(texte)]


def branchement(fichier: Path, texte: str, base: Path, rapport: Rapport) -> None:
    if fichier.suffix in {".json", ".html"}:
        return
    entree = _point_d_entree(fichier, texte, base)
    noms = [fichier.stem] if fichier.suffix in {".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".vue",
                                                ".svelte", ".sh"} else [fichier.name]
    refs = [(f, n, t) for f, n, t in chercher(base, noms, mot=fichier.suffix != ".css", fixe=True)
            if f != fichier and not est_test(f, base)]
    imports = [r for r in refs if _IMPORT.search(r[2])]
    if imports:
        rapport.ok("integrated: used by " + ", ".join(sorted({f"{relatif(f, base)}:{n}" for f, n, _ in imports})[:4]))
    elif entree:
        rapport.ok(f"integrated: {entree}")
    elif refs:
        rapport.alerte("mentioned but never imported/loaded",
                       [f"{relatif(f, base)}:{n}: {t[:100]}" for f, n, t in refs[:5]])
    else:
        rapport.echec("NOT integrated: no file of the project imports, loads or runs it",
                      ["wire it where it is needed (import/route/script tag), or delete it if it is not"])


def symboles_inutilises(fichier: Path, texte: str, base: Path, rapport: Rapport) -> None:
    symboles = [(n, l) for n, l in _symboles(fichier, texte) if n not in {"main"} and not n.startswith("test")]
    if not symboles or est_test(fichier, base):
        return
    occurrences: dict[str, int] = {}
    for _, _, ligne in chercher(base, [n for n, _ in symboles]):
        for nom, _ in symboles:
            if re.search(rf"\b{re.escape(nom)}\b", ligne):
                occurrences[nom] = occurrences.get(nom, 0) + 1
    morts = [f"l.{l} {n}" for n, l in symboles if occurrences.get(n, 0) <= 1]
    if morts:
        rapport.alerte(f"{len(morts)} function/class defined but never used anywhere", morts)
    else:
        rapport.ok(f"all {len(symboles)} top-level functions/classes are used")

