"""Mode hybride — en mode projet, l'agent local pilote et Claude Haiku écrit le code (`confier_a_haiku`).

Une consigne au socle ne suffisait pas (« Tetris test hybride aveugle », 2026-11-11) : le 35B suivait la méthode
« écris le fichier, teste-le » et écrivait lui-même page et style, à ~21 tokens/s, sans jamais appeler Haiku.
La règle est donc tenue par le harnais : en mode hybride, une écriture de fichier par l'agent local au-delà d'un
petit correctif est refusée et renvoyée vers `confier_a_haiku`. Coupé par `MODE_HYBRIDE=0`, ou si le relais
Claude Code n'est pas configuré.
"""

from __future__ import annotations

import os
import re

from backend.outils.contrat import ContexteExecution

# Au-delà, ce n'est plus un correctif : c'est du code, et il revient à Haiku.
CORRECTIF_MAX = 400

REFUS = ("HYBRID MODE: you do not write code yourself (you are slow at it). Call `confier_a_haiku` with the job "
         "described generically (files, roles, interfaces, tests); the harness writes Haiku's files into the "
         "project. Only fixes under {n} characters are yours.")


def disponible() -> bool:
    """Relais Claude Code configuré et mode non coupé."""
    configure = os.environ.get("RESUMEUR_URL", "").strip() and os.environ.get("RESUMEUR_JETON", "").strip()
    return bool(configure) and os.environ.get("MODE_HYBRIDE", "1").strip() != "0"


def refuse(contexte: ContexteExecution, taille: int) -> str | None:
    """Le message de refus si cette écriture revient à Haiku, sinon `None`."""
    if contexte.projet and taille > CORRECTIF_MAX and disponible():
        return REFUS.format(n=CORRECTIF_MAX)
    return None


# Écrire un fichier par le shell (`cat > f <<EOF`, `tee f`, `printf … > f`) contournait le refus
# (« Tetris test hybride aveugle 2 » : index.html écrit par un heredoc de 1 600 caractères).
_ECRITURE_SHELL = re.compile(r"<<|\btee\b|>\s*[\w./-]+\.(?:js|ts|tsx|jsx|py|html|css|json|md|sh)\b")


def refuse_commande(contexte: ContexteExecution, commande: str) -> str | None:
    """Le refus si la commande écrit du code par le shell au-delà d'un correctif, sinon `None`."""
    if _ECRITURE_SHELL.search(commande):
        return refuse(contexte, len(commande))
    return None
