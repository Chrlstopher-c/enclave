"""En mode projet, la relance nomme le dernier appel joué et, s'il a échoué, cite son erreur."""

from __future__ import annotations

from backend.inference import harnais
from backend.inference.fin_projet import EXTRAIT_ECHEC_MAX, DernierAppel, rappel_dernier_appel

PAUSE = "La base de données n'est pas initialisée au démarrage de l'application."


def _etat(dernier: DernierAppel | None) -> harnais.EtatBoucle:
    etat = harnais.EtatBoucle(harnais=harnais.FORGE, outils_declares=None, mode_projet=True)
    etat.aboutis = 3
    etat.dernier_appel = dernier
    return etat


def test_pause_apres_echec_cite_la_fin_de_l_erreur() -> None:
    sortie = "x" * 2000 + " FAILED tests/test_api.py::test_lister - sqlite3.OperationalError: no such table: todos"
    consigne = harnais.consigne_de_relance(PAUSE, _etat(DernierAppel("executer_commande", False, sortie)),
                                           avec_outils=True)
    assert consigne is not None and consigne.startswith(harnais.CONSIGNE_SUITE_PROJET)
    assert "`executer_commande`" in consigne and "FAILED" in consigne
    assert "no such table: todos" in consigne, "la QUEUE de la sortie porte l'erreur"
    assert len(consigne) < len(harnais.CONSIGNE_SUITE_PROJET) + EXTRAIT_ECHEC_MAX + 300


def test_pause_apres_succes_nomme_l_appel_sans_erreur() -> None:
    consigne = harnais.consigne_de_relance(PAUSE, _etat(DernierAppel("ecrire_fichier", True, "Écrit.")),
                                           avec_outils=True)
    assert consigne is not None and "`ecrire_fichier`" in consigne and "FAILED" not in consigne


def test_annonce_en_mode_projet_porte_aussi_le_rappel() -> None:
    etat = _etat(DernierAppel("executer_commande", False, "ModuleNotFoundError: fastapi"))
    consigne = harnais.consigne_de_relance("Je vais installer les dépendances.", etat, avec_outils=True)
    assert consigne is not None and "ModuleNotFoundError: fastapi" in consigne


def test_hors_mode_projet_ou_sans_appel_rien_n_est_ajoute() -> None:
    assert rappel_dernier_appel(None) == ""
    etat = harnais.EtatBoucle(harnais=harnais.FORGE, outils_declares=None)
    etat.dernier_appel = DernierAppel("executer_commande", False, "boom")
    consigne = harnais.consigne_de_relance("Je vais corriger le fichier.", etat, avec_outils=True)
    assert consigne is not None and "boom" not in consigne


def test_tour_muet_en_mode_projet_porte_le_rappel() -> None:
    etat = _etat(DernierAppel("executer_commande", False, "ImportError: cannot import name app"))
    consigne = harnais.consigne_de_relance("<think>…</think>", etat, avec_outils=True)
    assert consigne is not None and consigne.startswith(harnais.CONSIGNE_TOUR_MUET)
    assert "cannot import name app" in consigne
