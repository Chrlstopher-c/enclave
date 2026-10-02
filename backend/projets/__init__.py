"""Domaine `projets` — dossiers de l'hôte confiés à une conversation pour y construire une application.

Interface publique : ce que le chat et l'inférence ont le droit d'utiliser. Le reste est interne.
"""

from backend.projets.modeles import LiaisonProjet
from backend.projets.racine import ProjetInvalide, ProjetsDesactives, catalogue, chemin_projet


def instantane_avant_tour(nom: str, message: str) -> None:
    """Instantané non bloquant pris par le harnais avant un tour. Import tardif : `instantanes` dépend
    du client de l'atelier (`backend.outils`), qui dépend lui-même du chat — l'importer ici bouclerait."""
    from backend.projets.instantanes import prendre_sans_echec

    prendre_sans_echec(nom, message)


__all__ = ["LiaisonProjet", "ProjetInvalide", "ProjetsDesactives", "catalogue", "chemin_projet",
           "instantane_avant_tour"]
