"""Le quota de relances sur annonce se réarme après un appel d'outil joué."""

from __future__ import annotations

from backend.inference import harnais

ANNONCE = "Les fichiers sont prêts. Je lance les tests."


def _relance(etat: harnais.EtatBoucle, i: int) -> str | None:
    return harnais.consigne_de_relance(f"{ANNONCE} ({i})", etat, avec_outils=True)


def test_quota_epuise_sans_appel_puis_reamorce_apres_un_appel() -> None:
    etat = harnais.EtatBoucle(harnais=harnais.FORGE, outils_declares=None)
    assert all(_relance(etat, i) is not None for i in range(3))
    assert _relance(etat, 3) is None, "trois annonces sans appel : clôture"
    harnais.rearmer_relances(etat)
    etat.promesse_en_suspens = False
    assert _relance(etat, 4) is not None, "après un appel joué, une annonce est relancée à nouveau"


def test_mode_projet_une_pause_courte_apres_travail_est_relancee() -> None:
    etat = harnais.EtatBoucle(harnais=harnais.FORGE, outils_declares=None, mode_projet=True)
    etat.aboutis = 2
    pause = "<think>…</think>Je dois réinstaller les dépendances dans le venv correctement."
    assert harnais.consigne_de_relance(pause, etat, avec_outils=True) == harnais.CONSIGNE_SUITE_PROJET


def test_mode_projet_un_vrai_bilan_termine() -> None:
    etat = harnais.EtatBoucle(harnais=harnais.FORGE, outils_declares=None, mode_projet=True)
    etat.aboutis = 5
    bilan = "Bilan : l'API FastAPI, la page et 6 tests pytest sont en place. " * 8
    assert harnais.consigne_de_relance(bilan, etat, avec_outils=True) is None


def test_hors_mode_projet_une_reponse_courte_termine() -> None:
    etat = harnais.EtatBoucle(harnais=harnais.FORGE, outils_declares=None)
    etat.aboutis = 1
    reponse = "Il fait 18 °C à Paris aujourd’hui, ciel dégagé et vent faible toute la journée. " * 2
    assert harnais.consigne_de_relance(reponse, etat, avec_outils=True) is None
