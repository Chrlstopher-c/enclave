"""Maison de l'agent : accès par `~agent/`, écriture limitée, index et bloc de socle bornés."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.agent import bloc_socle, memoire, racine, skills
from backend.core.config import reset_settings_cache
from backend.outils.awareness import contenu
from backend.outils.bac_a_sable import CheminHorsBac, resoudre_dans_bac, verifier_ecriture
from backend.outils.contrat import ContexteExecution, EchecOutil
from backend.outils.explorer_bac import OUTIL_CHERCHER
from backend.outils.fichiers_bac import OUTIL_ECRIRE
from backend.outils.plan_fichier import plan
from backend.outils.registre import descriptions


@pytest.fixture
def maison(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ECHOHUB_AGENT_DIR", str(tmp_path / "agent"))
    reset_settings_cache()
    base = racine()
    (base / "memoire" / "prefs.md").write_text("---\nname: prefs\ndescription: Chris veut du Bun\n---\nBun.\n")
    (base / "skills" / "deployer").mkdir()
    (base / "skills" / "deployer" / "SKILL.md").write_text("---\nname: deployer\ndescription: Déployer\n---\n1.\n")
    yield base
    reset_settings_cache()


def _contexte(tmp_path: Path) -> ContexteExecution:
    (tmp_path / "bac").mkdir(exist_ok=True)
    return ContexteExecution(conversation_id="c", racine_bac=tmp_path / "bac")


def test_prefixe_resout_dans_la_maison_et_reste_confine(maison: Path, tmp_path: Path) -> None:
    assert resoudre_dans_bac(tmp_path, "~agent/SYSTEM.md") == maison / "SYSTEM.md"
    with pytest.raises(CheminHorsBac):
        resoudre_dans_bac(tmp_path, "~agent/../../etc/passwd")


def test_ecriture_limitee_a_memoire_skills_notes(maison: Path, tmp_path: Path) -> None:
    verifier_ecriture(maison / "memoire" / "x.md")
    with pytest.raises(CheminHorsBac):
        verifier_ecriture(maison / "SYSTEM.md")
    with pytest.raises(EchecOutil):
        asyncio.run(OUTIL_ECRIRE.executer({"chemin": "~agent/SYSTEM.md", "contenu": "pirate"}, _contexte(tmp_path)))
    asyncio.run(OUTIL_ECRIRE.executer({"chemin": "~agent/memoire/n.md", "contenu": "ok"}, _contexte(tmp_path)))
    assert (maison / "memoire" / "n.md").read_text() == "ok"


def test_recherche_dans_la_maison_rend_des_chemins_prefixes(maison: Path, tmp_path: Path) -> None:
    sortie = asyncio.run(OUTIL_CHERCHER.executer({"texte": "bun", "motif": "~agent/memoire/*"}, _contexte(tmp_path)))
    assert "~agent/memoire/prefs.md:" in sortie


def test_index_et_bloc_de_socle(maison: Path) -> None:
    assert [e.nom for e in memoire()] == ["prefs"] and [e.nom for e in skills()] == ["deployer"]
    bloc = bloc_socle()
    assert "prefs — Chris veut du Bun (~agent/memoire/prefs.md)" in bloc
    assert "deployer — Déployer" in bloc and "STANDING INSTRUCTIONS" in bloc
    assert "NEVER read it whole" in bloc


def test_plan_markdown_et_python() -> None:
    md = plan("# A\ntexte\n## B\nx\n# C\n", ".md")
    assert "- A  [lines 1-4]" in md and "  - B  [lines 3-4]" in md and "- C  [lines 5-5]" in md
    py = plan("class K:\n    def f(self):\n        pass\ndef g():\n    pass\n", ".py")
    assert "class K  [lines 1-3]" in py and "def g  [lines 4-5]" in py


def test_awareness_decrit_les_outils_reels(maison: Path) -> None:
    texte = contenu(descriptions(), "spoofer")
    assert "### plan_fichier" in texte and "### suivre_taches" in texte
    assert "## Skills" in texte and "deployer" in texte
