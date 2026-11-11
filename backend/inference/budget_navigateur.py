"""Budget de navigateur — le test dans le navigateur est un test de fumée, pas une séance de jeu.

« Tetris test hybride aveugle 2 » (2026-11-11) : le code était écrit et ses tests verts, et le 35B a encore fait
~50 appels `playwright` (parties jouées, pixels du canvas comptés, « game over » pris pour un bug). La méthode
le disait déjà ; le harnais le tient : au-delà du plafond, plus d'appel au navigateur tant que rien n'a changé
dans le code. Une écriture, une modification ou une délégation rouvre un budget complet (on revérifie après).
"""

from __future__ import annotations

import json
from typing import Any

PLAFOND = 10
_CHANGEMENTS = frozenset({"ecrire_fichier", "ecrire_fichiers", "modifier_fichier", "confier_a_haiku", "deleguer_code"})

REFUS = (f"HARNESS: {PLAFOND} browser calls since the last code change: the smoke test is over. Page loads, "
         "console checked, main action tried — that is enough; logic is proven by unit tests. Do not play, do not "
         "count pixels. If you saw a real bug, fix it (or delegate the fix), which reopens the browser; otherwise "
         "write the final report now.")


def est_navigateur(nom: str, arguments: Any) -> bool:
    """Un appel à l'outil `playwright` via MCP."""
    if nom != "mcp_appeler":
        return False
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return False
    serveur = arguments.get("serveur") or arguments.get("server") if isinstance(arguments, dict) else None
    return serveur == "playwright"


def est_changement(nom: str) -> bool:
    return nom in _CHANGEMENTS
