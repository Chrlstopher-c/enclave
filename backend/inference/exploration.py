"""Série d'exploration — beaucoup de lectures d'affilée sans rien écrire ni exécuter.

L'anti-redite ne voit que les sorties IDENTIQUES. Le 9B (« Tetris test », 2026-11-11) variait ses commandes
(`ls -la`, `ls -laR ..`, `find . -maxdepth 2`, `cat` d'un journal…) : chaque sortie était neuve, aucune ne le
faisait avancer. Une série de lectures n'est pas une faute en soi (comprendre un projet en demande), mais au-delà
d'un seuil le modèle est rappelé à l'action, une fois par palier.
"""

from __future__ import annotations

import json
import re
from typing import Any

SEUIL_SERIE = 8
_LECTURES = frozenset({"lire_fichier", "lister_fichiers", "chercher_dans_fichiers", "plan_fichier", "mcp_outils"})
_COMMANDES_LECTURE = frozenset({"ls", "find", "cat", "head", "tail", "wc", "grep", "rg", "tree", "pwd", "echo",
                                "stat", "file", "du", "df", "ps", "ss", "which", "less", "sort", "uniq", "cut"})
_SEPARATEURS = re.compile(r"&&|\|\||[;|\n]")


def _commande_lecture(commande: str) -> bool:
    """Chaque segment de la commande ne fait que lire (`cd` mis à part)."""
    segments = [s.split() for s in _SEPARATEURS.split(commande) if s.strip()]
    mots = [s[0] for s in segments if s and s[0] != "cd"]
    return bool(mots) and all(m in _COMMANDES_LECTURE for m in mots)


def est_lecture(nom: str, arguments: Any) -> bool:
    """L'appel ne fait que regarder : il ne change rien et ne prouve rien."""
    if nom in _LECTURES:
        return True
    if nom not in ("executer_commande", "run_command"):
        return False
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return False
    if not isinstance(arguments, dict):
        return False
    commande = arguments.get("commande") or arguments.get("command")
    return isinstance(commande, str) and _commande_lecture(commande)


def avis(serie: int) -> str | None:
    """Rappel ajouté au résultat quand la série atteint un palier (8, 16, 24…), sinon rien."""
    if serie < SEUIL_SERIE or serie % SEUIL_SERIE:
        return None
    return (f"HARNESS: {serie} look-only calls in a row, nothing written, edited or run. You most likely know "
            "enough: decide and act now (write, edit, run the test). Read more only for one precise missing fact.")
