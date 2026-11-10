"""Un seul `system`, en tête : sinon le gabarit Qwen 3.5 refuse la requête (2026-11-10, après compaction)."""

from __future__ import annotations

from backend.inference.engines_adapters.contrat import MessageChat
from backend.inference.forme_messages import un_seul_systeme


def test_resume_de_compaction_fusionne_et_system_tardif_rendu_user() -> None:
    messages = [MessageChat(role="system", content="socle"), MessageChat(role="system", content="[RÉSUMÉ] fait"),
                MessageChat(role="user", content="demande"), MessageChat(role="system", content="note tardive")]
    sortie = un_seul_systeme(messages)
    assert [m.role for m in sortie] == ["system", "user", "user"]
    assert sortie[0].content == "socle\n\n[RÉSUMÉ] fait" and sortie[2].content == "note tardive"
    assert messages[3].role == "system", "l'original ne bouge pas"


def test_rien_a_faire_rend_la_meme_suite() -> None:
    messages = [MessageChat(role="system", content="socle"), MessageChat(role="user", content="a")]
    assert un_seul_systeme(messages) == messages
