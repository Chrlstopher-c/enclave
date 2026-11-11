"""Fixtures des commandes : base jetable du domaine chat, et moteur simulé installé à la place du vrai."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from backend.chat import port_inference
from backend.chat.tests.conftest import base, chemin_base, conversation  # noqa: F401 — fixtures partagées
from backend.commandes.tests.faux import MoteurSimule


@pytest.fixture
def moteur(monkeypatch: pytest.MonkeyPatch) -> Iterator[MoteurSimule]:
    faux = MoteurSimule()
    monkeypatch.setattr(port_inference, "obtenir_moteur", lambda: faux)
    yield faux
