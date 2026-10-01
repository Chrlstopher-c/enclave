"""Preuves du mode projet côté outils : on travaille DANS le dossier du projet, et pas ailleurs."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest

from backend.chat.modeles import ResumeConversation
from backend.core.config import reset_settings_cache
from backend.outils import registre
from backend.outils.contrat import ContexteExecution


@pytest.fixture
def contexte_projet(conversation: ResumeConversation, tmp_path: Path,
                    monkeypatch: pytest.MonkeyPatch) -> Iterator[ContexteExecution]:
    base = tmp_path / "projets"
    (base / "app").mkdir(parents=True)
    monkeypatch.setenv("ECHOHUB_PROJETS_RACINE", str(base))
    reset_settings_cache()
    yield ContexteExecution(conversation_id=conversation.id, racine_bac=base / "app", projet="app")
    reset_settings_cache()


def _appel(nom: str, arguments: dict[str, object], contexte: ContexteExecution) -> registre.ResultatOutil:
    return asyncio.run(registre.executer(nom, arguments, contexte))


def test_ecrire_puis_executer_dans_le_projet(contexte_projet: ContexteExecution) -> None:
    ecrit = _appel("ecrire_fichier", {"chemin": "src/main.py", "contenu": "print('ok')\n"}, contexte_projet)
    assert ecrit.succes and "Déposé" not in ecrit.texte, "pas de carte de conversation en mode projet"
    assert (contexte_projet.racine_bac / "src" / "main.py").is_file()
    sortie = _appel("executer_commande", {"commande": "python3 src/main.py && pwd"}, contexte_projet)
    assert sortie.succes and "ok" in sortie.texte and sortie.texte.count("/app") >= 1


def test_sortir_du_projet_est_refuse(contexte_projet: ContexteExecution) -> None:
    refus = _appel("executer_commande", {"commande": "cd .. && ls"}, contexte_projet)
    assert not refus.succes and "sort de ton dossier" in refus.texte
    reserve = _appel("ecrire_fichier", {"chemin": ".echohub/x", "contenu": "x"}, contexte_projet)
    assert not reserve.succes


def test_lister_elague_les_dependances(contexte_projet: ContexteExecution) -> None:
    racine = contexte_projet.racine_bac
    (racine / "node_modules" / "pkg").mkdir(parents=True)
    (racine / "node_modules" / "pkg" / "index.js").write_text("x")
    (racine / "index.ts").write_text("x")
    liste = _appel("lister_fichiers", {}, contexte_projet)
    assert "index.ts" in liste.texte and "node_modules" not in liste.texte


def test_lire_par_tranches(contexte_projet: ContexteExecution) -> None:
    (contexte_projet.racine_bac / "long.txt").write_text("".join(f"ligne {i}\n" for i in range(1, 101)))
    extrait = _appel("lire_fichier", {"chemin": "long.txt", "ligne_debut": 95}, contexte_projet)
    assert extrait.texte.startswith("[à partir de la ligne 95 sur 100]") and "ligne 94\n" not in extrait.texte
