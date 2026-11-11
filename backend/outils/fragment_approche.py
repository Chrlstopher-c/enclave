"""Retrouver le fragment à remplacer quand le modèle l'a recopié sans ses accents.

Relevé sur « TestSetup » (11/11/2026) : « Categories » tapé pour « Catégories », la modification
échoue, et il faut trois relectures du fichier pour la refaire. Le texte exact reste la règle ; la
recherche sans accents n'est qu'un repli, et seulement quand elle désigne UN passage sans ambiguïté.
"""

from __future__ import annotations

import unicodedata


def _plier(texte: str) -> tuple[str, list[int]]:
    """Le texte sans accents, et pour chaque caractère plié l'indice du caractère d'origine."""
    plie: list[str] = []
    origine: list[int] = []
    for indice, caractere in enumerate(texte):
        for morceau in unicodedata.normalize("NFD", caractere):
            if unicodedata.category(morceau) != "Mn":
                plie.append(morceau)
                origine.append(indice)
    return "".join(plie), origine


def localiser_sans_accents(texte: str, fragment: str) -> tuple[int, int] | None:
    """Début et fin du passage de `texte` égal à `fragment` aux accents près, s'il est unique."""
    texte_plie, origine = _plier(texte)
    fragment_plie, _ = _plier(fragment)
    if not fragment_plie or texte_plie.count(fragment_plie) != 1:
        return None
    debut = texte_plie.index(fragment_plie)
    fin = debut + len(fragment_plie) - 1
    return origine[debut], origine[fin] + 1
