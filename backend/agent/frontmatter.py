"""En-tête YAML minimal (`---` … `---`) des fichiers de mémoire et de skills : `nom: valeur` par ligne."""

from __future__ import annotations


def lire(texte: str) -> tuple[dict[str, str], str]:
    """(champs, corps). Sans en-tête valide : ({}, texte entier)."""
    if not texte.startswith("---"):
        return {}, texte
    fin = texte.find("\n---", 3)
    if fin == -1:
        return {}, texte
    champs: dict[str, str] = {}
    for ligne in texte[3:fin].splitlines():
        cle, sep, valeur = ligne.partition(":")
        if sep and cle.strip() and not ligne.startswith((" ", "\t")):
            champs[cle.strip()] = valeur.strip().strip("'\"")
    return champs, texte[fin + 4:].lstrip("\n")


__all__ = ["lire"]
