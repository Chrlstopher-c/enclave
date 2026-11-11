"""Écriture groupée en texte brut : aucun échappement, donc plus de `\"\"\"` abîmé ni de fichier tronqué (2026-11-11)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from backend.inference.activite import chemin_courant, fichiers_termines
from backend.outils.contrat import ContexteExecution
from backend.outils.ecriture_groupee import OUTIL, sections

TEXTE = ('=== FILE: app/config.py ===\nclass Config:\n    """Settings: "quoted" \\\\ ok."""\n'
         '=== FILE: app/hub.py ===\nX = "a"\n')


def test_sections_gardent_le_contenu_brut() -> None:
    fichiers = sections(TEXTE)
    assert [f["chemin"] for f in fichiers] == ["app/config.py", "app/hub.py"]
    assert fichiers[0]["contenu"] == 'class Config:\n    """Settings: "quoted" \\\\ ok."""\n'


def test_l_outil_ecrit_les_fichiers_tels_quels(tmp_path: Path) -> None:
    contexte = ContexteExecution(conversation_id="c", racine_bac=tmp_path)
    asyncio.run(OUTIL.executer({"fichiers": TEXTE}, contexte))
    assert '"""Settings: "quoted"' in next(tmp_path.rglob("config.py")).read_text()


def test_la_liste_json_reste_acceptee(tmp_path: Path) -> None:
    contexte = ContexteExecution(conversation_id="c", racine_bac=tmp_path)
    asyncio.run(OUTIL.executer({"fichiers": [{"chemin": "a.py", "contenu": "A = 1\n"}]}, contexte))
    assert next(tmp_path.rglob("a.py")).read_text() == "A = 1\n"


def test_ecriture_anticipee_sur_flux_json_partiel() -> None:
    partiel = json.dumps({"fichiers": TEXTE})[:-12]  # le second fichier n'est pas fini
    termines = fichiers_termines(partiel)
    assert [f["chemin"] for f in termines] == ["app/config.py"]
    assert '"quoted"' in termines[0]["contenu"]
    assert chemin_courant(partiel) == "app/hub.py"


def test_ecriture_anticipee_sur_xml_brut() -> None:
    brut = "<parameter=fichiers>\n" + TEXTE
    assert [f["chemin"] for f in fichiers_termines(brut)] == ["app/config.py"]
