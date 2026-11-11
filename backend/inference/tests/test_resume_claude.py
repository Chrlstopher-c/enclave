"""Le résumé de compaction passe par Claude Haiku (relais de l'hôte) et retombe sur le modèle local sinon."""

from __future__ import annotations

import asyncio

import pytest

import backend.inference.resume_claude as resume_claude
import backend.inference.resume_compaction as resume_compaction


def _jouer(monkeypatch: pytest.MonkeyPatch, relais: str | None) -> tuple[str | None, list[str]]:
    vus: list[str] = []

    async def faux_relais(systeme: str, corps: str) -> str | None:
        vus.append(corps)
        return relais

    async def faux_local(messages: object, max_tokens: int) -> str | None:
        return "résumé local"

    monkeypatch.setattr(resume_claude, "resumer", faux_relais)
    monkeypatch.setattr(resume_compaction, "_resume_local", faux_local)
    return asyncio.run(resume_compaction.produire_resume("tour ancien", "", "", 4000)), vus


def test_haiku_resume_quand_le_relais_repond(monkeypatch: pytest.MonkeyPatch) -> None:
    texte, vus = _jouer(monkeypatch, "résumé haiku")
    assert texte == "résumé haiku" and "<transcript>" in vus[0]


def test_repli_local_quand_le_relais_echoue(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _jouer(monkeypatch, None)[0] == "résumé local"


def test_sans_jeton_aucun_appel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESUMEUR_JETON", raising=False)
    assert asyncio.run(resume_claude.resumer("s", "c")) is None
