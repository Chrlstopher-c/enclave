"""`/compact [instructions]` : compaction immédiate de la branche, consigne transmise au résumeur."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from backend.chat import depot, port_inference
from backend.chat.compaction_manuelle import compacter_maintenant
from backend.chat.erreurs import BrancheInvalide
from backend.chat.modeles import ResumeConversation
from backend.chat.port_inference import MessageInference, OccupationContexte


class _Moteur:
    def __init__(self) -> None:
        self.consignes: list[str] = []

    async def mesurer_occupation(self, messages: Sequence[MessageInference]) -> OccupationContexte:
        tokens = sum(len(m.contenu) for m in messages)
        return OccupationContexte(mesurable=True, contexte_total=100_000, tokens_mesures=tokens,
                                  tokens_libres=100_000 - tokens)

    async def resumer(self, a_resumer: str, precedent: str, langue: str, max_tokens: int,
                      consigne: str = "") -> str | None:
        self.consignes.append(consigne)
        return "RÉSUMÉ"


@pytest.fixture
def moteur(monkeypatch: pytest.MonkeyPatch) -> _Moteur:
    faux = _Moteur()
    monkeypatch.setattr(port_inference, "obtenir_moteur", lambda: faux)
    return faux


def _echanges(conversation: ResumeConversation, n: int) -> None:
    parent = None
    for i in range(n):
        parent = depot.ajouter_message(conversation.id, "user" if i % 2 == 0 else "assistant",
                                       f"message {i}", parent_id=parent).id


def test_compaction_manuelle_sans_seuil_et_avec_consigne(conversation: ResumeConversation, moteur: _Moteur) -> None:
    _echanges(conversation, 8)
    info = asyncio.run(compacter_maintenant(conversation.id, "garde la liste des routes"))
    assert info.nb_messages_resumes == 6, "seuls les 2 derniers messages restent mot pour mot"
    assert moteur.consignes == ["garde la liste des routes"]
    assert depot.lire_compaction_active(conversation.id, {info.coupe_message_id}) is not None


def test_trop_peu_d_echanges_est_refuse(conversation: ResumeConversation, moteur: _Moteur) -> None:
    _echanges(conversation, 2)
    with pytest.raises(BrancheInvalide):
        asyncio.run(compacter_maintenant(conversation.id))
