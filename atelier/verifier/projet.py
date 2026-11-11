"""Racine du projet, fichiers sources, recherche (ripgrep) et exécution bornée des commandes."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

MARQUEURS = (".git", "pyproject.toml", "package.json", "requirements.txt", "README.md")
IGNORES = ("node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".git", ".echohub", ".next",
           ".cache", "coverage", "target")
SOURCES = {".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".sh", ".json", ".html", ".css", ".vue", ".svelte"}
EXCLUS_RG = [arg for nom in IGNORES for arg in ("-g", f"!{nom}/")]


def racine(depart: Path) -> Path:
    """Premier dossier (en remontant) qui porte un marqueur de projet ; sinon le dossier courant."""
    for dossier in (depart, *depart.parents):
        if any((dossier / m).exists() for m in MARQUEURS):
            return dossier
        if dossier == Path("/projets") or dossier.parent == Path("/projets"):
            return dossier
    return Path.cwd()


def lancer(cmd: list[str], cwd: Path, delai: int = 120) -> tuple[int, str]:
    """(code, sortie fusionnée) ; une commande absente ou trop longue devient un code 127/124."""
    try:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=delai)
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not installed"
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {delai}s"
    return res.returncode, (res.stdout + res.stderr).strip()


def fichiers_sources(base: Path) -> list[Path]:
    code, sortie = lancer(["rg", "--files", "--no-require-git", *EXCLUS_RG], base)
    if code not in (0, 1):
        return []
    return sorted(base / l for l in sortie.splitlines() if Path(l).suffix in SOURCES)


def fichiers_modifies(base: Path) -> list[Path]:
    """Fichiers modifiés ou nouveaux selon git ; liste vide hors dépôt git."""
    if not (base / ".git").exists() or not shutil.which("git"):
        return []
    code, sortie = lancer(["git", "status", "--porcelain", "--untracked-files=all"], base)
    if code != 0:
        return []
    chemins = [base / l[3:].split(" -> ")[-1] for l in sortie.splitlines() if l[:2].strip() != "D"]
    return [c for c in chemins if c.is_file() and c.suffix in SOURCES]


def chercher(base: Path, motifs: list[str], mot: bool = True, fixe: bool = True) -> list[tuple[Path, int, str]]:
    """Occurrences (fichier, ligne, texte) de l'un des motifs dans le projet."""
    if not motifs:
        return []
    cmd = ["rg", "-n", "--no-heading", "--no-require-git", "--max-columns", "200", *EXCLUS_RG]
    cmd += (["-w"] if mot else []) + (["-F"] if fixe else [])
    for motif in motifs:
        cmd += ["-e", motif]
    code, sortie = lancer(cmd, base)
    if code not in (0, 1):
        return []
    trouves = []
    for ligne in sortie.splitlines():
        fichier, _, reste = ligne.partition(":")
        num, _, texte = reste.partition(":")
        if num.isdigit():
            trouves.append((base / fichier, int(num), texte.strip()))
    return trouves


def relatif(chemin: Path, base: Path) -> str:
    try:
        return str(chemin.relative_to(base))
    except ValueError:
        return str(chemin)
