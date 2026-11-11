"""Bloc d'environnement du mode projet : où l'agent se trouve et ce que contient son dossier.

Constaté le 2026-11-10 : six appels (`ls`, `pwd`, `ls ./tui-test`…) pour apprendre ce que le harnais
savait déjà. Les harnais d'agents courants donnent ce bloc d'emblée ; l'agent démarre « dans son corps ».
L'arborescence est triée et bornée : stable d'un message à l'autre tant que le projet ne bouge pas,
pour ne pas casser le cache de préfixe du moteur.
"""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

from backend.outils.explorer_bac import DOSSIERS_IGNORES

ENTREES_MAX = 40
# Matériel de l'hôte confié à l'atelier (antenne Wi-Fi, docker/wifi) : une information sur l'environnement,
# pas un outil — l'agent s'en sert par le shell comme de n'importe quelle commande. Décrit dans le .env.
VARIABLE_MATERIEL = "ECHOHUB_ATELIER_MATERIEL"


def ligne_materiel() -> str:
    """« Hardware: … » si un matériel est déclaré, sinon vide."""
    texte = os.environ.get(VARIABLE_MATERIEL, "").strip()
    return f"Hardware available in your shell: {texte}" if texte else ""


def bloc_materiel() -> str:
    """Bloc `<env>` réduit au matériel, pour une conversation sans projet."""
    ligne = ligne_materiel()
    return f"<env>\n{ligne}\n</env>" if ligne else ""


def _entrees(dossier: Path, profondeur: int) -> list[str]:
    lignes: list[str] = []
    for chemin in sorted(dossier.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if chemin.name.startswith(".") and chemin.name not in (".env.example", ".gitignore"):
            continue
        if chemin.is_dir():
            if chemin.name in DOSSIERS_IGNORES or chemin.name.endswith("venv"):
                continue
            lignes.append(f"{chemin.name}/")
            if profondeur > 1:
                lignes.extend(f"  {ligne}" for ligne in _entrees(chemin, profondeur - 1))
        else:
            lignes.append(chemin.name)
    return lignes


def bloc_environnement(racine: Path, projet: str) -> str:
    """Dossier courant + arborescence sur deux niveaux ; vide si le dossier est illisible."""
    try:
        lignes = _entrees(racine, 2)
    except OSError as exc:
        logger.warning("Arborescence du projet {} illisible : {}", projet, exc)
        return ""
    reste = len(lignes) - ENTREES_MAX
    arbre = "\n".join(lignes[:ENTREES_MAX]) or "(empty folder)"
    if reste > 0:
        arbre += f"\n… {reste} more (use list_files)"
    materiel = ligne_materiel()
    return (f"<env>\nWorking directory: /projets/{projet} (already the shell's cwd; use relative paths)\n"
            f"Scratch space: /tmp\n{materiel + chr(10) if materiel else ''}Files:\n{arbre}\n</env>")


__all__ = ["bloc_environnement", "bloc_materiel", "ligne_materiel"]
