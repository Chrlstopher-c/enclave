"""`suivre_taches` : liste remplacée en entier, raison exigée pour bloquer ou abandonner."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.outils.contrat import ContexteExecution, EchecOutil
from backend.outils.suivre_taches import OUTIL, taches_ouvertes


def _contexte(tmp_path: Path, conversation: str = "conv-taches") -> ContexteExecution:
    return ContexteExecution(conversation_id=conversation, racine_bac=tmp_path)


def _appeler(arguments: dict, contexte: ContexteExecution) -> str:
    return asyncio.run(OUTIL.executer(arguments, contexte))


def test_liste_rendue_et_taches_ouvertes(tmp_path: Path) -> None:
    contexte = _contexte(tmp_path)
    sortie = _appeler({"taches": [{"titre": "Squelette", "etat": "fait"}, {"titre": "API", "etat": "en_cours"},
                                  {"titre": "Tests", "etat": "a_faire"}]}, contexte)
    assert sortie.startswith("Tâches (1/3 faites)") and "[x] Squelette" in sortie and "[>] API" in sortie
    assert taches_ouvertes("conv-taches") == ["API", "Tests"]
    _appeler({"todos": [{"titre": "API", "etat": "fait"}, {"titre": "Tests", "etat": "abandonne",
                                                            "raison": "hors périmètre"}]}, contexte)
    assert taches_ouvertes("conv-taches") == []


def test_bloque_sans_raison_refuse_et_etat_inconnu_refuse(tmp_path: Path) -> None:
    with pytest.raises(EchecOutil):
        _appeler({"taches": [{"titre": "Clé Stripe", "etat": "bloque"}]}, _contexte(tmp_path, "c2"))
    with pytest.raises(EchecOutil):
        _appeler({"taches": [{"titre": "X", "etat": "presque"}]}, _contexte(tmp_path, "c2"))
    assert taches_ouvertes("c2") == []
