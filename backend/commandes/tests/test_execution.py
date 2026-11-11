"""Exécution des commandes : tâche détachée, progression publiée, conversation occupée pendant la commande."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.chat import annulation, depot, diffusion, generation
from backend.chat import effacement
from backend.chat.erreurs import BrancheInvalide, GenerationDejaEnCours
from backend.chat.modeles import DemandeGeneration, ResumeConversation
from backend.commandes import execution, progression
from backend.commandes.catalogue import CommandeInvalide
from backend.commandes.tests.faux import MoteurSimule


def _echanges(conversation_id: str, n: int) -> None:
    parent = None
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        parent = depot.ajouter_message(conversation_id, role, f"message {i}", parent_id=parent).id


async def _collecter(publication: diffusion.Diffusion) -> list[Any]:
    return [evenement async for evenement in publication.abonner()]


def test_compact_va_au_bout_sans_auditeur_et_publie_sa_progression(
    conversation: ResumeConversation, moteur: MoteurSimule
) -> None:
    _echanges(conversation.id, 8)

    async def scenario() -> tuple[list[Any], Any]:
        lancement = await execution.lancer(conversation.id, "compact", "garde la liste des routes")
        assert lancement.tache is not None
        publication = diffusion.en_cours(conversation.id)
        assert publication is not None
        recu = asyncio.ensure_future(_collecter(publication))
        info = await lancement.tache
        return await recu, info

    recu, info = asyncio.run(scenario())
    assert info.nb_messages_resumes == 6
    assert moteur.consignes == ["garde la liste des routes"]
    assert [e.type for e in recu][-2:] == ["compaction", "commande"]
    assert recu[0].commande["etat"] == "en_cours"
    assert recu[-1].commande["etat"] == "termine"
    assert [e.commande["etape"] for e in recu if e.type == "commande"][1] == "preparation"
    assert len(depot.lire_compactions(conversation.id)) == 1
    assert diffusion.en_cours(conversation.id) is None
    assert not annulation.est_active(conversation.id)


def test_un_client_qui_se_raccroche_recoit_la_suite_puis_la_fin(
    conversation: ResumeConversation, moteur: MoteurSimule, monkeypatch: pytest.MonkeyPatch
) -> None:
    _echanges(conversation.id, 8)
    monkeypatch.setattr(progression, "INTERVALLE_BATTEMENT_S", 0.02)
    moteur.attente_s = 0.2

    async def scenario() -> tuple[list[Any], Any]:
        lancement = await execution.lancer(conversation.id, "compact", "")
        await asyncio.sleep(0.05)  # le client est parti puis revient pendant le résumé
        publication = diffusion.en_cours(conversation.id)
        assert publication is not None
        recu = await _collecter(publication)
        return recu, await lancement.tache

    recu, _ = asyncio.run(scenario())
    commandes = [e.commande for e in recu if e.type == "commande"]
    assert any(c["etape"] == "resume" for c in commandes), "la phase de résumé est rejouée au client"
    assert any(e.type == "compaction" for e in recu)
    assert commandes[-1]["etat"] == "termine"


def test_pendant_une_commande_generer_rejouer_et_compacter_sont_refuses(
    conversation: ResumeConversation, moteur: MoteurSimule
) -> None:
    _echanges(conversation.id, 8)
    moteur.attente_s = 0.2

    async def scenario() -> None:
        lancement = await execution.lancer(conversation.id, "compact", "")
        with pytest.raises(GenerationDejaEnCours):
            generation.preparer(conversation.id, DemandeGeneration(contenu="bonjour"))
        with pytest.raises(GenerationDejaEnCours):
            await execution.lancer(conversation.id, "compact", "")
        with pytest.raises(GenerationDejaEnCours):
            await execution.lancer(conversation.id, "clear", "")
        assert lancement.tache is not None
        await lancement.tache

    asyncio.run(scenario())
    assert len(depot.lister_messages(conversation.id)) == 8, "rien n'a été écrit pendant la commande"


def test_echec_du_resume_publie_une_commande_en_echec_et_libere_la_conversation(
    conversation: ResumeConversation, moteur: MoteurSimule
) -> None:
    _echanges(conversation.id, 8)
    moteur.resume = None

    async def scenario() -> list[Any]:
        lancement = await execution.lancer(conversation.id, "compact", "")
        publication = diffusion.en_cours(conversation.id)
        assert publication is not None
        recu = asyncio.ensure_future(_collecter(publication))
        assert lancement.tache is not None
        with pytest.raises(BrancheInvalide):
            await lancement.tache
        return await recu

    recu = asyncio.run(scenario())
    derniere = recu[-1].commande
    assert recu[-1].type == "commande" and derniere["etat"] == "echec"
    assert derniere["erreur"], "l'échec dit ce qu'il faut faire"
    assert not annulation.est_active(conversation.id)


def test_compact_sur_conversation_vide_est_refuse_avant_toute_reservation(conversation: ResumeConversation) -> None:
    with pytest.raises(BrancheInvalide):
        asyncio.run(execution.lancer(conversation.id, "compact", ""))
    assert not annulation.est_active(conversation.id)


def test_clear_pose_une_ancre_sans_tache_et_refuse_les_arguments(
    conversation: ResumeConversation, monkeypatch: pytest.MonkeyPatch
) -> None:
    _echanges(conversation.id, 2)

    class _Effacement:
        def model_dump(self, mode: str = "python") -> dict[str, str]:
            return {"id": "e1", "ancre_message_id": "m2", "cree_le": "2026-11-11T10:00:00+00:00"}

    monkeypatch.setattr(effacement, "effacer", lambda _conversation_id: _Effacement())
    lancement = asyncio.run(execution.lancer(conversation.id, "clear", ""))
    assert lancement.tache is None and lancement.effacement is not None
    assert lancement.effacement["id"] == "e1"
    with pytest.raises(CommandeInvalide):
        asyncio.run(execution.lancer(conversation.id, "clear", "tout"))
