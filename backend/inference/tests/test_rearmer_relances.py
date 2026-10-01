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
