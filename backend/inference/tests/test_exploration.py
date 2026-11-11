"""Série d'exploration : rappel à l'action après une longue suite de lectures."""

from backend.inference import exploration


def test_commandes_de_lecture_reconnues() -> None:
    assert exploration.est_lecture("executer_commande", {"commande": "cd .atelier && ls -la && find . -maxdepth 2"})
    assert exploration.est_lecture("executer_commande", '{"commande": "cat log.txt | tail -5"}')
    assert exploration.est_lecture("lire_fichier", {"chemin": "a.py"})


def test_commandes_qui_agissent_non_comptees() -> None:
    assert not exploration.est_lecture("executer_commande", {"commande": "node --test tests/"})
    assert not exploration.est_lecture("executer_commande", {"commande": "ls && rm -rf build"})
    assert not exploration.est_lecture("ecrire_fichier", {"chemin": "a.py", "contenu": "x"})


def test_avis_par_palier() -> None:
    assert exploration.avis(exploration.SEUIL_SERIE - 1) is None
    assert "look-only" in (exploration.avis(exploration.SEUIL_SERIE) or "")
    assert exploration.avis(exploration.SEUIL_SERIE + 1) is None
    assert exploration.avis(exploration.SEUIL_SERIE * 2) is not None
