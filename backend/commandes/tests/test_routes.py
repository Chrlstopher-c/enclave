"""Routes `/chat/commandes` : catalogue, 202 immédiat pour /compact, 200 pour /clear, codes d'erreur du contrat."""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.chat import annulation, depot, diffusion
from backend.chat.modeles import ResumeConversation
from backend.commandes import routes
from backend.commandes.tests.faux import MoteurSimule


def _client() -> TestClient:
    application = FastAPI()
    application.include_router(routes.routeur)
    return TestClient(application)


def _echanges(conversation_id: str, n: int) -> None:
    parent = None
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        parent = depot.ajouter_message(conversation_id, role, f"message {i}", parent_id=parent).id


def test_get_commandes_rend_le_catalogue(base: Any) -> None:
    reponse = _client().get("/chat/commandes")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert [c["nom"] for c in corps] == ["compact", "clear"]
    assert corps[0]["usage"] == "/compact [instructions]" and corps[0]["arguments"] is True
    assert corps[1]["arguments"] is False


def test_compact_rend_202_et_la_tache_finit_sans_auditeur(
    conversation: ResumeConversation, moteur: MoteurSimule
) -> None:
    _echanges(conversation.id, 8)
    with _client() as client:
        reponse = client.post(f"/chat/conversations/{conversation.id}/commandes", json={"nom": "compact"})
        assert reponse.status_code == 202
        corps = reponse.json()
        assert corps["nom"] == "compact" and corps["commande_id"]
        for _ in range(200):
            if not annulation.est_active(conversation.id):
                break
            time.sleep(0.02)
    assert len(depot.lire_compactions(conversation.id)) == 1
    assert diffusion.en_cours(conversation.id) is None


def test_clear_rend_200_avec_son_effacement(
    conversation: ResumeConversation, monkeypatch: Any
) -> None:
    from backend.chat import effacement

    _echanges(conversation.id, 2)

    class _Effacement:
        def model_dump(self, mode: str = "python") -> dict[str, str]:
            return {"id": "e1", "ancre_message_id": "m2", "cree_le": "2026-11-11T10:00:00+00:00"}

    monkeypatch.setattr(effacement, "effacer", lambda _conversation_id: _Effacement())
    reponse = _client().post(f"/chat/conversations/{conversation.id}/commandes", json={"nom": "clear"})
    assert reponse.status_code == 200
    assert reponse.json()["effacement"]["ancre_message_id"] == "m2"


def test_commande_inconnue_rend_404_au_format_du_contrat(conversation: ResumeConversation) -> None:
    reponse = _client().post(f"/chat/conversations/{conversation.id}/commandes", json={"nom": "xyz"})
    assert reponse.status_code == 404
    assert reponse.json() == {"detail": "Commande inconnue : /xyz"}


def test_clear_avec_arguments_rend_422(conversation: ResumeConversation) -> None:
    _echanges(conversation.id, 2)
    reponse = _client().post(f"/chat/conversations/{conversation.id}/commandes",
                             json={"nom": "clear", "arguments": "tout"})
    assert reponse.status_code == 422


def test_compact_pendant_une_generation_rend_409(conversation: ResumeConversation) -> None:
    _echanges(conversation.id, 8)
    annulation.reserver(conversation.id, "message-en-cours")
    reponse = _client().post(f"/chat/conversations/{conversation.id}/commandes", json={"nom": "compact"})
    assert reponse.status_code == 409
