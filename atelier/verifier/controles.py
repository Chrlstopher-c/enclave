"""Syntaxe et lint d'un fichier : compile Python, node/bun pour JS/TS, bash -n, JSON ; ruff, eslint."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from projet import lancer
from rapport import Rapport

_JS = {".js", ".mjs", ".cjs", ".jsx"}
_TS = {".ts", ".tsx"}
_PROBLEME = re.compile(r":\d+:\d+:? ")


def _erreur_syntaxe(fichier: Path, texte: str, base: Path) -> str | None:
    suffixe = fichier.suffix
    if suffixe == ".py":
        try:
            compile(texte, str(fichier), "exec")
        except SyntaxError as exc:
            return f"l.{exc.lineno}: {exc.msg}"
        return None
    if suffixe == ".json":
        try:
            json.loads(texte)
        except json.JSONDecodeError as exc:
            return f"l.{exc.lineno}: {exc.msg}"
        return None
    if suffixe == ".sh":
        cmd = ["bash", "-n", str(fichier)]
    elif suffixe in _JS | _TS and shutil.which("bun"):
        cmd = ["bun", "build", "--no-bundle", str(fichier)]
    elif suffixe in _JS:
        cmd = ["node", "--check", str(fichier)]
    else:
        return None
    code, sortie = lancer(cmd, base, 60)
    if code == 0 or code == 127:
        return None
    utiles = [l.strip() for l in sortie.splitlines() if "error" in l.lower() or l.strip().startswith("at ")]
    return " ".join(utiles or sortie.splitlines()[-2:])[:400]


def syntaxe(fichier: Path, texte: str, base: Path, rapport: Rapport) -> bool:
    erreur = _erreur_syntaxe(fichier, texte, base)
    if erreur:
        rapport.echec("syntax", [erreur])
        return False
    rapport.ok("syntax")
    return True


def _outil(base: Path, nom: str) -> str | None:
    for candidat in (base / ".venv" / "bin" / nom, base / "node_modules" / ".bin" / nom):
        if candidat.exists():
            return str(candidat)
    return shutil.which(nom)


def lint(fichier: Path, base: Path, rapport: Rapport) -> None:
    if fichier.suffix == ".py":
        ruff = _outil(base, "ruff")
        if not ruff:
            rapport.alerte("lint skipped: ruff missing (pip install ruff)")
            return
        code, sortie = lancer([ruff, "check", "--no-cache", "--output-format", "concise",
                               "--select", "E,F,W,B,UP,SIM", "--ignore", "E501", str(fichier)], base)
    elif fichier.suffix in _JS | _TS and _outil(base, "eslint") and any(base.glob("eslint.config.*")):
        code, sortie = lancer([_outil(base, "eslint") or "eslint", "--format", "unix", str(fichier)], base)
    else:
        return
    problemes = [l for l in sortie.splitlines() if _PROBLEME.search(l)]
    if code == 0 and not problemes:
        rapport.ok("lint")
    else:
        corrigeables = any("[*]" in p for p in problemes)
        conseil = [f"auto-fix the [*] ones: ruff check --fix {fichier.name}"] if corrigeables else []
        details = conseil + [p.replace(str(base) + "/", "") for p in problemes]
        rapport.echec(f"lint: {len(problemes)} problem(s)", details)


def typescript(base: Path, fichiers: list[Path]) -> list[str]:
    """Erreurs `tsc --noEmit` du projet qui concernent les fichiers vérifiés (vide sans tsc/tsconfig)."""
    tsc = _outil(base, "tsc")
    if not tsc or not (base / "tsconfig.json").exists():
        return []
    _, sortie = lancer([tsc, "--noEmit", "--pretty", "false", "-p", str(base)], base, 180)
    noms = {str(f.relative_to(base)) for f in fichiers}
    return [l for l in sortie.splitlines() if l.split("(")[0] in noms]
