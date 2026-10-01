"""L'annonce à l'impératif pluriel, sans pronom, est une promesse comme une autre."""

from __future__ import annotations

import pytest

from backend.inference.reprise import promesse_non_tenue


@pytest.mark.parametrize("texte", [
    "Le requirements.txt est OK. Corrigeons tout et créons la page manquante.",
    "Les dépendances sont là. Lançons les tests.",
    "Maintenant, vérifions que le serveur répond.",
])
def test_imperatif_pluriel_detecte(texte: str) -> None:
    assert promesse_non_tenue(texte)


@pytest.mark.parametrize("texte", [
    "Les 4 tests passent et le serveur répond sur le port 8000.",
    "Nous avons terminé : l'API et la page fonctionnent.",
    "Voilà les questions que nous nous posons.",
])
def test_bilan_non_detecte(texte: str) -> None:
    assert not promesse_non_tenue(texte)
