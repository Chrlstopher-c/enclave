"""Un retour relit la conversation côté serveur et garde un exemple autonome."""

from __future__ import annotations

import pytest

from backend.chat.depot import ajouter_message, ecrire_reglages
from backend.chat.modeles import ReglagesConversation, ResumeConversation
from backend.retours import depot, service
from backend.retours.modeles import DemandeRetour
from backend.retours.service import RetourInvalide

SYSTEME = "Tu es un copywriter expert."


def _tour(conversation: ResumeConversation) -> tuple[str, str]:
    ecrire_reglages(conversation.id, ReglagesConversation(prompt_systeme=SYSTEME))
    brief = ajouter_message(conversation.id, "user", "Produit : X")
    reponse = ajouter_message(conversation.id, "assistant", "plan</think>\n\nTexte", parent_id=brief.id)
    return brief.id, reponse.id


def test_note_une_reponse_avec_son_contexte(conversation: ResumeConversation) -> None:
    _, reponse_id = _tour(conversation)
    retour = service.noter(DemandeRetour(conversation_id=conversation.id, message_id=reponse_id, verdict="positif"))
    assert retour.prompt_systeme == SYSTEME
    assert [t.contenu for t in retour.historique] == ["Produit : X"]
    assert retour.reponse.endswith("Texte")


def test_le_dernier_verdict_remplace_le_precedent(conversation: ResumeConversation) -> None:
    _, reponse_id = _tour(conversation)
    for verdict in ("negatif", "correction"):
        service.noter(DemandeRetour(conversation_id=conversation.id, message_id=reponse_id, verdict=verdict,
                                    correction="Mieux" if verdict == "correction" else None))
    retours = depot.lister(conversation.id)
    assert len(retours) == 1 and retours[0].correction == "Mieux"
    assert service.resumer(conversation.id).par_message == {reponse_id: "correction"}


def test_refuse_de_noter_un_message_utilisateur(conversation: ResumeConversation) -> None:
    brief_id, _ = _tour(conversation)
    with pytest.raises(RetourInvalide):
        service.noter(DemandeRetour(conversation_id=conversation.id, message_id=brief_id, verdict="positif"))


def test_une_correction_vide_est_refusee() -> None:
    with pytest.raises(ValueError):
        DemandeRetour(conversation_id="c", message_id="m", verdict="correction", correction="  ")


def test_meilleure_variante_unique_par_tour(conversation: ResumeConversation) -> None:
    brief_id, premiere = _tour(conversation)
    seconde = ajouter_message(conversation.id, "assistant", "autre</think>\n\nTexte 2", parent_id=brief_id).id
    for message_id in (premiere, seconde):
        service.noter(DemandeRetour(conversation_id=conversation.id, message_id=message_id, verdict="meilleure"))
    assert service.resumer(conversation.id).par_message == {seconde: "meilleure"}


def test_une_iteration_porte_son_rang(conversation: ResumeConversation) -> None:
    _, reponse_id = _tour(conversation)
    revision = ajouter_message(conversation.id, "user", "Plus court", parent_id=reponse_id)
    seconde = ajouter_message(conversation.id, "assistant", "ok</think>\n\nCourt", parent_id=revision.id)
    retour = service.noter(DemandeRetour(conversation_id=conversation.id, message_id=seconde.id, verdict="negatif",
                                         raisons=["ton"]))
    assert retour.tour == 1 and depot.lister(conversation.id)[0].raisons == ["ton"]


def test_les_verdicts_de_claude_ne_remplacent_pas_ceux_de_chris(conversation: ResumeConversation) -> None:
    _, reponse_id = _tour(conversation)
    service.noter(DemandeRetour(conversation_id=conversation.id, message_id=reponse_id, verdict="positif"))
    service.noter(DemandeRetour(conversation_id=conversation.id, message_id=reponse_id, verdict="negatif",
                                source="claude"))
    resume = service.resumer(conversation.id)
    assert resume.par_message == {reponse_id: "positif"} and resume.claude_par_message == {reponse_id: "negatif"}
