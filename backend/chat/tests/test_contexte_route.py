"""Le panneau mesure ce que la génération enverrait vraiment : socle, outils, historique (2026-11-10)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.chat import port_inference, routes
from backend.chat.generation import _ContexteConstruit
from backend.chat.port_inference import MessageInference


class _Moteur:
    def __init__(self) -> None:
        self.vus: list[Any] = []

    async def mesurer_detail(self, messages: list[MessageInference]) -> dict[str, object]:
        self.vus.append(messages)
        return {"mesurable": True, "tokens_mesures": 42}


def test_la_mesure_part_du_contexte_de_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    moteur = _Moteur()
    monkeypatch.setattr(port_inference, "obtenir_moteur", lambda: moteur)
    monkeypatch.setattr(routes.depot, "exiger_conversation", lambda _id: None)
    monkeypatch.setattr(routes.depot, "feuille_active", lambda _id: None)
    monkeypatch.setattr(routes.depot, "lire_compaction_active", lambda _id, _ids: None)
    contexte = _ContexteConstruit(entete="SOCLE + OUTILS", ancres=[], messages=[], outils_actifs=None, projet=None)
    monkeypatch.setattr("backend.chat.generation.contexte_de_branche", lambda _id, _f: contexte)
    assert asyncio.run(routes.mesurer_contexte("c1")) == {"mesurable": True, "tokens_mesures": 42}
    assert moteur.vus[0][0].role == "system" and moteur.vus[0][0].contenu == "SOCLE + OUTILS"
