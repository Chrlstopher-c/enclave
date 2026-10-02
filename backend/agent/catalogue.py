"""Index de la mémoire et liste des skills, tels que le socle les présente — courts, bornés."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from backend.agent import frontmatter
from backend.agent.maison import racine

ENTREES_MAX = 40
DESCRIPTION_MAX = 160


@dataclass(frozen=True)
class Entree:
    nom: str
    description: str
    chemin: str  # relatif à la maison, préfixe `~agent/` compris


def _entree(fichier: Path, base: Path, nom_defaut: str) -> Entree | None:
    try:
        champs, corps = frontmatter.lire(fichier.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Entrée illisible {} : {}", fichier, exc)
        return None
    description = champs.get("description") or next((l.strip() for l in corps.splitlines() if l.strip()), "")
    return Entree(nom=champs.get("name") or nom_defaut, description=description[:DESCRIPTION_MAX],
                  chemin=f"~agent/{fichier.relative_to(base).as_posix()}")


def memoire() -> list[Entree]:
    base = racine()
    fichiers = sorted((base / "memoire").glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [e for f in fichiers[:ENTREES_MAX] if (e := _entree(f, base, f.stem))]


def skills() -> list[Entree]:
    base = racine()
    fichiers = sorted((base / "skills").glob("*/SKILL.md"))
    return [e for f in fichiers[:ENTREES_MAX] if (e := _entree(f, base, f.parent.name))]


__all__ = ["Entree", "memoire", "skills"]
