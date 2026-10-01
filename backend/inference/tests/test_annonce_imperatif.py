"""L'annonce à l'impératif pluriel, sans pronom, est une promesse comme une autre."""

from __future__ import annotations

import pytest

from backend.inference.reprise import promesse_non_tenue


@pytest.mark.parametrize("texte", [
    "Le requirements.txt est OK. Corrigeons tout et créons la page manquante.",
    "Les dépendances sont là. Lançons les tests.",
    "Maintenant, vérifions que le serveur répond.",
    "Parfait. Je lis le code actuel pour savoir comment le corriger.",
    "Je vais vérifier que l'API répond.",
    "Je lance tout en une seule commande :\n\n```bash\npip install fastapi && pytest -q\n```",
    "Bien, passons à l'exécution : installation puis tests.\n\n```bash\npip install fastapi && pytest\n```",
    "```bash\npython3 -m venv .venv && pytest -q\n```",
    "Je vois le problème. Je vais appeler explicitement `init_db()` au début de chaque route API.",
    "Les fichiers ne sont pas à l'endroit supposé. Laissez-moi les retrouver.",
    "Le cd a échoué.\n\n```bash\nexecuter_commande commande=\"pwd && ls\"\n```",
])
def test_imperatif_pluriel_detecte(texte: str) -> None:
    assert promesse_non_tenue(texte)


@pytest.mark.parametrize("texte", [
    "Les 4 tests passent et le serveur répond sur le port 8000.",
    "Nous avons terminé : l'API et la page fonctionnent.",
    "Voilà les questions que nous nous posons.",
    "J'ai vérifié : les 4 tests passent.",
    "J'ai remplacé `TemplateResponse` et modifié les routes : les 9 tests passent.",
    "I fixed the routes and replaced the template engine; all 9 tests pass.",
    "Tout est vert. Pour lancer l'app :\n\n```bash\nuvicorn main:app --port 8000\n```",
])
def test_bilan_non_detecte(texte: str) -> None:
    assert not promesse_non_tenue(texte)
