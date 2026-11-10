"""Route des messages glissés pendant le travail (2026-11-10)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.chat import annulation, routes
from backend.chat.routes import ConsigneGlissee
from backend.inference import consignes


def test_refusee_sans_generation_acceptee_pendant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes.depot, "exiger_conversation", lambda _id: None)
    corps = ConsigneGlissee(id="k1", texte="Utilise pnpm")
    monkeypatch.setattr(annulation, "est_active", lambda _id: False)
    assert asyncio.run(routes.glisser_consigne("c1", corps)) == {"acceptee": False}
    monkeypatch.setattr(annulation, "est_active", lambda _id: True)
    assert asyncio.run(routes.glisser_consigne("c1", corps)) == {"acceptee": True}
    lues: list[Any] = consignes.prendre("c1")
    assert [c.texte for c in lues] == ["Utilise pnpm"]
