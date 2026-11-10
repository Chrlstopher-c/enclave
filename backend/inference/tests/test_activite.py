"""Activité en direct : fichier en cours, fichiers groupés complets sauvés tôt, débit, phase.

Photo de Chris du 2026-11-10 : « Écriture groupée php/ARCHITECTURE.md », puis quinze minutes muettes
et « Le moteur n'a rien émis depuis 900 s » — tout ce qui avait été écrit était perdu.
"""

from __future__ import annotations

import asyncio
import json

from backend.inference.activite import SuiviActivite, chemin_courant, fichiers_termines, progression

ARGS = json.dumps({"fichiers": [{"chemin": "a.py", "contenu": "x = {1: 2}\n"},
                                {"chemin": "b/c.py", "contenu": "print(\"}\")\n"}]})


def test_seuls_les_fichiers_complets_sont_rendus_json_et_xml() -> None:
    partiel = ARGS[: ARGS.index('"b/c.py"') + 30]
    assert [f["chemin"] for f in fichiers_termines(partiel)] == ["a.py"]
    assert [f["chemin"] for f in fichiers_termines(ARGS)] == ["a.py", "b/c.py"]
    xml = "<tool_call>\n<function=ecrire_fichiers>\n<parameter=fichiers>\n" + json.dumps(json.loads(ARGS)["fichiers"])
    assert [f["chemin"] for f in fichiers_termines(xml)] == ["a.py", "b/c.py"]


def test_le_fichier_en_cours_est_le_dernier_chemin_ecrit() -> None:
    assert chemin_courant(ARGS[: ARGS.index('"b/c.py"') + 10]) == "b/c.py"
    assert chemin_courant('{"fichiers": [') is None


def test_chaque_fichier_complet_est_ecrit_une_seule_fois() -> None:
    suivi, ecrits = SuiviActivite(), []

    async def ecrire(chemin: str, contenu: str) -> None:
        ecrits.append(chemin)

    async def jouer() -> None:
        for fin in (ARGS.index('"b/c.py"'), len(ARGS), len(ARGS)):
            await progression(suivi, {"jetons": 3, "outil": {"nom": "ecrire_fichiers", "brut": ARGS[:fin]}}, ecrire)

    asyncio.run(jouer())
    assert ecrits == ["a.py", "b/c.py"]
    instantane = suivi.instantane(force=True)
    assert instantane is not None and instantane["phase"] == "outil" and instantane["tokens"] == 9
    assert instantane["outil"]["fichiers_sauves"] == ["a.py", "b/c.py"]


def test_phase_reflexion_puis_texte_et_debit_par_progression() -> None:
    suivi = SuiviActivite()
    suivi.compter(1, progression=False)
    suivi.texte("<think>je réfléchis")
    assert suivi.phase == "reflexion"
    suivi.texte("</think>Réponse")
    assert suivi.phase == "texte"
    suivi.compter(5, progression=True)
    suivi.compter(1, progression=False)  # ignoré : le moteur compte par progressions
    assert suivi.jetons == 6


def test_les_instantanes_sont_espaces() -> None:
    suivi = SuiviActivite()
    assert suivi.instantane() is not None
    assert suivi.instantane() is None
    assert suivi.instantane(force=True) is not None
