"""Lance les tests qui visent le fichier (ceux qui le nomment), avec le Python ou le runner du projet."""

from __future__ import annotations

import shutil
from pathlib import Path

from integration import est_test
from projet import chercher, lancer, relatif
from rapport import Rapport

_DEJA_LANCES: dict[tuple[str, ...], tuple[int, str]] = {}


def _derniere_ligne(sortie: str) -> str:
    lignes = [l for l in sortie.splitlines() if l.strip()]
    return lignes[-1][:200] if lignes else "(no output)"


def _python(base: Path) -> str:
    venv = base / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else "python3"


def lancer_tests(fichier: Path, base: Path, rapport: Rapport) -> None:
    if est_test(fichier, base):
        tests = [fichier]
    else:
        tests = sorted({f for f, _, _ in chercher(base, [fichier.stem]) if est_test(f, base) and f != fichier})
    if not tests:
        if fichier.suffix in {".py", ".ts", ".js", ".tsx", ".jsx"} and not fichier.stem.startswith("__"):
            rapport.alerte("no test mentions this file", ["logic worth keeping deserves a test"])
        return
    noms = [relatif(t, base) for t in tests]
    if tuple(noms) in _DEJA_LANCES:
        code, sortie = _DEJA_LANCES[tuple(noms)]
    elif tests[0].suffix == ".py":
        code, sortie = lancer([_python(base), "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
                               *noms], base, 300)
        if "No module named pytest" in sortie:
            rapport.alerte("tests not run: pytest missing", [f"{_python(base)} -m pip install -q pytest"])
            return
    elif shutil.which("bun"):
        code, sortie = lancer(["bun", "test", *noms], base, 300)
    else:
        return
    _DEJA_LANCES[tuple(noms)] = (code, sortie)
    if code == 0:
        rapport.ok(f"tests: {', '.join(noms[:3])} → {_derniere_ligne(sortie)}")
    else:
        erreurs = [l for l in sortie.splitlines() if l.startswith(("E ", "FAILED", "ERROR")) or "error:" in l]
        rapport.echec(f"tests FAIL: {', '.join(noms[:3])} → {_derniere_ligne(sortie)}", erreurs[:10])
