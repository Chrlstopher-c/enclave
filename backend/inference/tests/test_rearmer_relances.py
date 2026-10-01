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
    pause = "<think>…</think>Les dépendances sont installées, mais le venv reste incomplet."
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


def test_mode_projet_quota_porte_a_six() -> None:
    etat = harnais.EtatBoucle(harnais=harnais.FORGE, outils_declares=None, mode_projet=True)
    assert all(_relance(etat, i) is not None for i in range(6))
    assert _relance(etat, 6) is None


FAUX_BILAN = (
    "## Ce qui a été fait\n- Remplacement de `TemplateResponse` par un `jinja2.Environment` classique.\n"
    "- Ajout d'un appel à `init_db()` dans chaque route API.\n" * 4
    + "\n## Ce qui reste à faire\n4 tests sur 9 passent. La commande suivante règle ce dernier point :\n"
    "```bash\nrm -f todos.db && .venv/bin/pytest tests/test_api.py -x\n```\n"
    "\n| Symptôme | Remède |\n|---|---|\n| Données persistantes | `rm -f todos.db` avant pytest |\n"
)


def test_mode_projet_bilan_avec_reste_faisable_est_relance_deux_fois() -> None:
    etat = harnais.EtatBoucle(harnais=harnais.FORGE, outils_declares=None, mode_projet=True)
    etat.aboutis = 27
    bilans = [f"Tour {i} — {FAUX_BILAN}" for i in range(3)]
    assert harnais.consigne_de_relance(bilans[0], etat, avec_outils=True) == harnais.CONSIGNE_RESTE_FAISABLE
    harnais.rearmer_relances(etat)
    assert harnais.consigne_de_relance(bilans[1], etat, avec_outils=True) == harnais.CONSIGNE_RESTE_FAISABLE
    harnais.rearmer_relances(etat)
    assert harnais.consigne_de_relance(bilans[2], etat, avec_outils=True) is None, "le quota ne se réarme pas"


def test_mode_projet_reste_qui_depend_de_l_utilisateur_termine() -> None:
    etat = harnais.EtatBoucle(harnais=harnais.FORGE, outils_declares=None, mode_projet=True)
    etat.aboutis = 8
    bilan = ("L'app est construite, 9 tests verts, serveur vérifié au curl sur le port 8000. " * 6
             + "\nCe qui reste à faire : renseigner ta clé Stripe dans `.env` (je ne l'ai pas).")
    assert harnais.consigne_de_relance(bilan, etat, avec_outils=True) is None


def test_mode_projet_pause_apres_un_appel_echoue_est_relancee() -> None:
    etat = harnais.EtatBoucle(harnais=harnais.FORGE, outils_declares=None, mode_projet=True)
    etat.echecs_vus.add("lire_fichier:todo-final/main.py")
    pause = "Les fichiers sont dans le bac mais pas à l'endroit supposé. Laissez-moi les retrouver."
    assert harnais.consigne_de_relance(pause, etat, avec_outils=True) is not None


def test_mode_projet_fin_au_futur_proche_est_une_annonce() -> None:
    etat = harnais.EtatBoucle(harnais=harnais.FORGE, outils_declares=None, mode_projet=True)
    etat.aboutis = 12
    texte = ("L'erreur est bien `no such table` dans `test_create`. " * 8
             + "Je vais essayer une approche plus directe : appeler init_db() au niveau du module.")
    assert harnais.consigne_de_relance(texte, etat, avec_outils=True) is not None
