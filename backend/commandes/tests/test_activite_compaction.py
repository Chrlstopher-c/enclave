"""Compaction de boucle : la phase `compaction` est publiée pendant le résumé, rafraîchie au fil de l'attente."""

from __future__ import annotations

import asyncio
from datetime import datetime
from collections.abc import Sequence
from typing import Any

import pytest

from backend.inference import activite, compaction_boucle
from backend.inference.activite import SuiviActivite
from backend.inference.compaction_boucle import compacter_si_besoin, demarrer
from backend.inference.engines_adapters.contrat import MessageChat, OccupationContexte

FENETRE = 1_000


class _Superviseur:
    async def compter_contexte(self, _socle: str, messages: Sequence[MessageChat]) -> OccupationContexte:
        tokens = sum(len(m.content) for m in messages if isinstance(m.content, str))
        return OccupationContexte(mesurable=True, contexte_total=FENETRE, tokens_mesures=tokens)


def _tache(n_tours: int) -> list[MessageChat]:
    messages = [MessageChat(role="system", content="SOCLE"), MessageChat(role="user", content="Fais une app.")]
    for i in range(n_tours):
        messages.append(MessageChat(role="assistant", content=f"tour {i} " + "a" * 40))
        messages.append(MessageChat(role="tool", content=f"sortie {i} " + "s" * 60))
    return messages


def test_la_phase_compaction_est_publiee_pendant_le_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compaction_boucle, "superviseur", _Superviseur())
    monkeypatch.setattr(activite, "INTERVALLE_BATTEMENT_S", 0.02)

    async def resume_lent(*_args: Any, **kwargs: Any) -> str:
        suivi = kwargs["suivi"]
        await suivi({"etape": "resume", "resumeur": "local"})
        await asyncio.sleep(0.15)
        await suivi({"tokens": 12, "tokens_par_seconde": 30.0})
        return "RÉSUMÉ"

    monkeypatch.setattr(compaction_boucle, "produire_resume", resume_lent)
    suivi_activite = SuiviActivite()

    async def scenario() -> list[dict[str, Any] | None]:
        messages = _tache(20)
        etat = demarrer(messages)
        etat.suivi = suivi_activite.suivre_compaction
        tache = asyncio.ensure_future(compacter_si_besoin(messages, etat, etape_terminee=True))
        instantanes = [i async for i in suivi_activite.battements(tache)]
        assert await tache is not None
        return instantanes

    instantanes = asyncio.run(scenario())
    phases = [i["phase"] for i in instantanes if i is not None]
    assert len(phases) >= 2 and set(phases) == {"compaction"}
    dernier = instantanes[-1]
    assert dernier is not None and dernier["compaction"]["resumeur"] == "local"
    assert suivi_activite.compaction is not None and suivi_activite.compaction["tokens"] == 12
    assert dernier["compaction"]["duree_ms"] > 0


def test_l_instantane_porte_le_debut_de_la_generation_et_le_garde_stable() -> None:
    suivi_activite = SuiviActivite()
    premier = suivi_activite.instantane(force=True)
    suivi_activite.jetons += 5
    second = suivi_activite.instantane(force=True)
    assert premier is not None and second is not None
    assert "debut" in premier and "debut" in second
    assert premier["debut"] == second["debut"] == suivi_activite.debut
    assert datetime.fromisoformat(premier["debut"]).tzinfo is not None
