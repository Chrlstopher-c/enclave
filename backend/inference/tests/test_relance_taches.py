"""Le tour ne finit pas sur une tâche ouverte ; la relance s'arrête si rien ne progresse."""

from __future__ import annotations

from backend.inference import harnais
from backend.inference.suivi_taches import RELANCES_TACHES_MAX

BILAN = ("J'ai construit l'API et ses tests ; tout passe, le serveur répond au curl sur le port 5000. " * 6)


def _etat(ouvertes: list[str] | None) -> harnais.EtatBoucle:
    etat = harnais.EtatBoucle(harnais=harnais.FORGE, outils_declares=None)
    etat.aboutis = 3
    etat.taches_ouvertes = ouvertes
    return etat


def test_bilan_avec_taches_ouvertes_est_relance() -> None:
    consigne = harnais.consigne_de_relance(BILAN, _etat(["Écrire le README"]), avec_outils=True)
    assert consigne is not None and "« Écrire le README »" in consigne


def test_sans_liste_tenue_dans_la_generation_rien_ne_change() -> None:
    assert harnais.consigne_de_relance(BILAN, _etat(None), avec_outils=True) is None
    assert harnais.consigne_de_relance(BILAN, _etat([]), avec_outils=True) is None


def test_relances_bornees_sans_progres_et_rearmees_par_un_progres() -> None:
    etat = _etat(["A", "B"])
    textes = [f"{BILAN} ({i})" for i in range(RELANCES_TACHES_MAX + 2)]
    assert all(harnais.consigne_de_relance(t, etat, avec_outils=True) for t in textes[:RELANCES_TACHES_MAX])
    assert harnais.consigne_de_relance(textes[RELANCES_TACHES_MAX], etat, avec_outils=True) is None
    etat.taches_ouvertes = ["B"]
    assert harnais.consigne_de_relance(textes[-1], etat, avec_outils=True) is not None, "une tâche fermée réarme"
