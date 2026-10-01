"""Autonomie en mode projet : pas de compte à rebours, et un fichier recopié dans le chat est relancé."""

from __future__ import annotations

from backend.inference import harnais
from backend.inference.budget_outils import avertissement_du_tour
from backend.inference.fin_projet import CONSIGNE_CODE_MONTRE, code_montre

FICHIER_RECOPIE = (
    "Je vois le problème : les imports sont décalés. Je vais corriger les fichiers.\n\n```python\n"
    + "".join(f"from .module{i} import nom{i}\n" for i in range(12))
    + "```\n"
)


def test_forge_ne_compte_pas_a_rebours_tous_les_dix_appels() -> None:
    etat = harnais.EtatBoucle(harnais=harnais.FORGE, outils_declares=None)
    avis = []
    for _ in range(60):
        etat.tours_faits += 1
        avis.append(avertissement_du_tour(etat))
    assert avis == [None] * 60


def test_forge_previent_seulement_avant_le_garde_fou_absolu() -> None:
    etat = harnais.EtatBoucle(harnais=harnais.FORGE, outils_declares=None)
    etat.tours_faits = harnais.FORGE.tours_absolus_max - 1
    assert avertissement_du_tour(etat) == harnais.CONSIGNE_DERNIER_TOUR


def test_harnais_borne_garde_son_avertissement() -> None:
    etat = harnais.EtatBoucle(harnais=harnais.ECHOHUB, outils_declares=None)
    etat.tours_faits = harnais.ECHOHUB.tours_outils_max - 1
    assert avertissement_du_tour(etat) is not None


def test_code_recopie_dans_le_chat_est_detecte() -> None:
    assert code_montre(FICHIER_RECOPIE)
    assert not code_montre("Pour lancer :\n```bash\n" + "echo x\n" * 12 + "```")
    assert not code_montre("Exemple :\n```python\nfrom spoofer import analyze\nanalyze('a.jpg')\n```")


def test_mode_projet_fichier_recopie_est_relance() -> None:
    etat = harnais.EtatBoucle(harnais=harnais.FORGE, outils_declares=None, mode_projet=True)
    etat.aboutis = 4
    consigne = harnais.consigne_de_relance(FICHIER_RECOPIE * 2, etat, avec_outils=True)
    assert consigne is not None and consigne.startswith(CONSIGNE_CODE_MONTRE)
