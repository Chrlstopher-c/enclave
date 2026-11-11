"""Effacement annulable (`/clear`) : une ancre sur la branche, et le contexte qui repart après elle."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from backend.chat import annulation, depot, effacement, generation, routes_effacements
from backend.chat.erreurs import BrancheInvalide, GenerationDejaEnCours
from backend.chat.modeles import InfoCompaction, ResumeConversation


def _ajouter(conversation_id: str, role: str, contenu: str) -> str:
    """Ajoute un message au bout de la branche active, comme le fait l'envoi normal."""
    message = depot.ajouter_message(conversation_id, role=role, contenu=contenu,
                                    parent_id=depot.feuille_active(conversation_id))
    return message.id


def _contenus(conversation_id: str, feuille: str | None) -> list[str]:
    """Contenus des messages que le moteur recevrait (socle exclu)."""
    contexte = generation.contexte_de_branche(conversation_id, feuille)
    return [ancre.message.contenu for ancre in contexte.ancres]


def _echanges(conversation_id: str, n: int) -> list[str]:
    return [_ajouter(conversation_id, "user" if i % 2 == 0 else "assistant", f"ancien {i}") for i in range(n)]


def test_effacer_puis_contexte_sans_anciens_messages(conversation: ResumeConversation) -> None:
    _echanges(conversation.id, 4)
    info = effacement.effacer(conversation.id)
    assert info.ancre_message_id == depot.feuille_active(conversation.id)
    assert _contenus(conversation.id, depot.feuille_active(conversation.id)) == []


def test_nouveau_message_apres_clear_seul_dans_le_contexte(conversation: ResumeConversation) -> None:
    _echanges(conversation.id, 4)
    effacement.effacer(conversation.id)
    _ajouter(conversation.id, "user", "nouveau")
    assert _contenus(conversation.id, depot.feuille_active(conversation.id)) == ["nouveau"]


def test_annuler_rend_tout_le_chemin(conversation: ResumeConversation) -> None:
    _echanges(conversation.id, 2)
    info = effacement.effacer(conversation.id)
    _ajouter(conversation.id, "user", "nouveau")
    effacement.annuler(conversation.id, info.id)
    assert _contenus(conversation.id, depot.feuille_active(conversation.id)) == ["ancien 0", "ancien 1", "nouveau"]


def test_deux_clears_annuler_le_dernier_revient_au_premier(conversation: ResumeConversation) -> None:
    _echanges(conversation.id, 2)
    premier = effacement.effacer(conversation.id)
    _ajouter(conversation.id, "user", "entre deux")
    second = effacement.effacer(conversation.id)
    _ajouter(conversation.id, "user", "après second")
    assert [e.id for e in effacement.lister(conversation.id)] == [premier.id, second.id]

    effacement.annuler(conversation.id, second.id)

    assert [e.id for e in effacement.lister(conversation.id)] == [premier.id]
    feuille = depot.feuille_active(conversation.id)
    assert _contenus(conversation.id, feuille) == ["entre deux", "après second"]


def test_effacer_conversation_vide_est_refuse(conversation: ResumeConversation) -> None:
    with pytest.raises(BrancheInvalide):
        effacement.effacer(conversation.id)


def test_generation_en_cours_refuse_effacer_et_annuler(conversation: ResumeConversation) -> None:
    _echanges(conversation.id, 2)
    info = effacement.effacer(conversation.id)
    annulation.reserver(conversation.id, "message-provisoire")
    with pytest.raises(GenerationDejaEnCours):
        effacement.effacer(conversation.id)
    with pytest.raises(GenerationDejaEnCours):
        effacement.annuler(conversation.id, info.id)


def test_compaction_anterieure_a_l_ancre_ignoree(conversation: ResumeConversation) -> None:
    ids = _echanges(conversation.id, 4)
    depot.enregistrer_compaction(_compaction(conversation.id, message=ids[-1], coupe=ids[0]))
    effacement.effacer(conversation.id)
    _ajouter(conversation.id, "user", "nouveau")
    contexte = generation.contexte_de_branche(conversation.id, depot.feuille_active(conversation.id))
    assert depot.lire_compaction_active(conversation.id, {a.id for a in contexte.ancres}) is None


def test_compaction_posterieure_a_l_ancre_conservee(conversation: ResumeConversation) -> None:
    ids = _echanges(conversation.id, 2)
    effacement.effacer(conversation.id)
    apres = _ajouter(conversation.id, "user", "nouveau")
    depot.enregistrer_compaction(_compaction(conversation.id, message=ids[-1], coupe=apres))
    contexte = generation.contexte_de_branche(conversation.id, depot.feuille_active(conversation.id))
    assert depot.lire_compaction_active(conversation.id, {a.id for a in contexte.ancres}) is not None


def test_routes_liste_puis_suppression_204(conversation: ResumeConversation) -> None:
    _echanges(conversation.id, 2)
    info = effacement.effacer(conversation.id)
    liste = asyncio.run(routes_effacements.lister_effacements(conversation.id))
    assert [e.id for e in liste] == [info.id]
    reponse = asyncio.run(routes_effacements.annuler_effacement(conversation.id, info.id))
    assert reponse.status_code == 204
    assert effacement.lister(conversation.id) == []


def test_route_suppression_inconnue_404(conversation: ResumeConversation) -> None:
    with pytest.raises(HTTPException) as erreur:
        asyncio.run(routes_effacements.annuler_effacement(conversation.id, "inconnu"))
    assert erreur.value.status_code == 404


def _compaction(conversation_id: str, *, message: str, coupe: str) -> InfoCompaction:
    return InfoCompaction(
        id=f"c-{coupe}", conversation_id=conversation_id, message_id=message, coupe_message_id=coupe,
        nb_messages_resumes=1, tokens_avant=10, tokens_apres=5, contexte_total=1000,
        resume="résumé", cree_le=datetime.now(timezone.utc),
    )
