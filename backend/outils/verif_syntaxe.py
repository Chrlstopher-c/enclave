"""Vérification de syntaxe immédiate après une écriture — le linter de l'agent.

Un fichier Python ou JSON cassé ne se révélait qu'au lancement suivant, parfois trois appels plus
tard, et l'erreur arrivait alors noyée dans un traceback d'import. Rendue dans la sortie même de
l'écriture, elle est corrigée au tour suivant, sur le bon fichier, à la bonne ligne.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath


def avis_syntaxe(chemin: str, texte: str) -> str:
    """Avertissement à ajouter à la sortie de l'outil, ou chaîne vide si rien n'est à signaler."""
    suffixe = PurePosixPath(chemin).suffix.lower()
    try:
        if suffixe == ".py":
            compile(texte, chemin, "exec")
        elif suffixe == ".json":
            json.loads(texte)
    except SyntaxError as exc:
        return (f"\nSYNTAX ERROR in {chemin}, line {exc.lineno}: {exc.msg}. The file is written but will "
                "not run: fix that line now with `modifier_fichier`.")
    except json.JSONDecodeError as exc:
        return (f"\nINVALID JSON in {chemin}, line {exc.lineno}: {exc.msg}. Fix it now with "
                "`modifier_fichier`.")
    return ""


__all__ = ["avis_syntaxe"]
