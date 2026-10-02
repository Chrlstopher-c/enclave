"""Le dossier de l'agent, partagé entre toutes ses conversations — l'équivalent de `~/.claude/`.

    SYSTEM.md            ses instructions permanentes (l'équivalent de CLAUDE.md), écrites par Chris
    AWARENESS.md         ce qu'il peut faire (outils, MCP, skills, projets) — régénéré, lu PAR SECTION
    AWARENESS.notes.md   ajouts manuels, recopiés à la fin d'AWARENESS.md
    memoire/<nom>.md     un fait par fichier, en-tête `name` / `description` ; l'index va dans le socle
    skills/<nom>/SKILL.md  une procédure réutilisable ; la liste va dans le socle, le corps se lit au besoin
    mcp.json             serveurs MCP à brancher

Le modèle y accède par le préfixe `~agent/` de ses outils de fichiers. Il ne peut ÉCRIRE que dans
`memoire/`, `skills/` et `notes/` : SYSTEM.md et la configuration restent à Chris.
"""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

from backend.core.config import get_settings

PREFIXE = "~agent/"
DOSSIERS_ECRITURE = frozenset({"memoire", "skills", "notes"})
SYSTEME = "SYSTEM.md"
AWARENESS = "AWARENESS.md"
AWARENESS_NOTES = "AWARENESS.notes.md"
MCP = "mcp.json"

_SYSTEME_INITIAL = """# SYSTEM.md — instructions permanentes de l'agent EchoHub

Ce fichier est lu au début de CHAQUE conversation (comme CLAUDE.md pour Claude Code). Garde-le court :
il est relu à chaque tour. Les détails vont dans des skills (`skills/<nom>/SKILL.md`) ou dans la mémoire.

## Préférences de Chris
- Répondre en français, aller à l'essentiel.
"""


def racine() -> Path:
    """Dossier de l'agent, créé et amorcé au besoin (SYSTEM.md, memoire/, skills/, notes/)."""
    dossier = get_settings().agent_dir
    try:
        for sous in DOSSIERS_ECRITURE:
            (dossier / sous).mkdir(parents=True, exist_ok=True)
        systeme = dossier / SYSTEME
        if not systeme.exists():
            systeme.write_text(_SYSTEME_INITIAL, encoding="utf-8")
            for sous in DOSSIERS_ECRITURE:
                attribuer(dossier / sous)
            attribuer(systeme)
    except OSError as exc:
        logger.error("Maison de l'agent inaccessible ({}) : {}", dossier, exc)
    return dossier.resolve()


def attribuer(chemin: Path) -> None:
    """Rend `chemin` (et ses dossiers jusqu'à la maison) au propriétaire configuré, s'il y en a un.

    Le backend Docker tourne en root : sans cela, SYSTEM.md et la mémoire deviendraient non éditables
    par Chris dans le dossier de l'hôte. Un échec se journalise, il ne bloque jamais l'écriture.
    """
    proprietaire = get_settings().agent_proprietaire.strip()
    if not proprietaire or os.geteuid() != 0:
        return
    uid, _, gid = proprietaire.partition(":")
    base = get_settings().agent_dir.resolve()
    try:
        courant = chemin.resolve()
        while courant == base or base in courant.parents:
            os.chown(courant, int(uid), int(gid or uid))
            if courant == base:
                break
            courant = courant.parent
    except (OSError, ValueError) as exc:
        logger.warning("Rétrocession de {} à {} impossible : {}", chemin, proprietaire, exc)


def ecriture_permise(relatif: Path) -> bool:
    """Le modèle peut-il écrire ce chemin, relatif à la maison ?"""
    return bool(relatif.parts) and relatif.parts[0] in DOSSIERS_ECRITURE and len(relatif.parts) > 1


def lire_texte(nom: str, plafond: int) -> str:
    """Contenu d'un fichier de la maison, borné ; chaîne vide s'il n'existe pas."""
    chemin = racine() / nom
    try:
        texte = chemin.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError as exc:
        logger.warning("Lecture de {} impossible : {}", chemin, exc)
        return ""
    if len(texte) <= plafond:
        return texte
    return f"{texte[:plafond]}\n[… tronqué : {len(texte) - plafond} caractères de plus, lire ~agent/{nom}]"


__all__ = ["AWARENESS", "AWARENESS_NOTES", "DOSSIERS_ECRITURE", "MCP", "PREFIXE", "SYSTEME",
           "attribuer", "ecriture_permise", "lire_texte", "racine"]
