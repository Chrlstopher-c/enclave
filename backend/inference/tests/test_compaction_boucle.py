"""Compaction PENDANT une tâche d'agent : la demande reste intacte, une relance ne la remplace pas."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest

from backend.inference import compaction_boucle, resume_compaction
from backend.inference.compaction_boucle import MARQUEUR_RESUME, compacter_si_besoin, demarrer
from backend.inference.engines_adapters.contrat import MessageChat, MorceauGeneration, OccupationContexte

FENETRE = 1_000  # seuils : étape 700, dur 800 ; budget de queue 300 tokens


class _FauxSuperviseur:
    """Un token par caractère ; le résumé cite ce qu'on lui donne à intégrer."""

    def __init__(self) -> None:
        self.precedents: list[str] = []
        self.systemes: list[str] = []

    async def compter_contexte(self, _socle: str, messages: Sequence[MessageChat]) -> OccupationContexte:
        tokens = sum(len(m.content) for m in messages if isinstance(m.content, str))
        return OccupationContexte(mesurable=True, contexte_total=FENETRE, tokens_mesures=tokens)

    def generer(self, messages: Sequence[MessageChat], options: Any,
                outils: Any = None) -> AsyncIterator[MorceauGeneration]:
        corps = str(messages[-1].content)
        self.precedents.append(corps)
        self.systemes.append(str(messages[0].content))
        return self._flux()

    async def _flux(self) -> AsyncIterator[MorceauGeneration]:
        yield MorceauGeneration(type="token", contenu="OBJECTIF: page todo. ÉTAT: API faite.")
        yield MorceauGeneration(type="fin", raison_arret="stop")


@pytest.fixture
def faux(monkeypatch: pytest.MonkeyPatch) -> _FauxSuperviseur:
    sup = _FauxSuperviseur()
    monkeypatch.setattr(compaction_boucle, "superviseur", sup)
    monkeypatch.setattr(resume_compaction, "superviseur", sup)
    return sup


def _tache(n_tours: int) -> list[MessageChat]:
    messages = [MessageChat(role="system", content="SOCLE"), MessageChat(role="user", content="Fais une app todo.")]
    for i in range(n_tours):
        messages.append(MessageChat(role="assistant", content=f"tour {i} " + "a" * 40))
        messages.append(MessageChat(role="tool", content=f"sortie {i} " + "s" * 60))
    return messages


def test_sous_le_seuil_rien_ne_bouge(faux: _FauxSuperviseur) -> None:
    messages = _tache(2)
    etat = demarrer(messages)
    assert asyncio.run(compacter_si_besoin(messages, etat, etape_terminee=True)) is None
    assert len(messages) == 6


def test_au_dela_du_seuil_dur_la_tache_est_compactee(faux: _FauxSuperviseur) -> None:
    messages = _tache(10)
    demande = messages[1]
    etat = demarrer(messages)
    messages.append(MessageChat(role="user", content="Relance du harnais : appelle un outil."))
    messages.append(MessageChat(role="assistant", content="dernier tour"))
    messages.append(MessageChat(role="tool", content="dernière sortie"))
    note = asyncio.run(compacter_si_besoin(messages, etat, etape_terminee=False, taches="[x] API\n[ ] Tests"))
    assert note is not None and "compacté" in note
    assert messages[0].content == "SOCLE"
    assert messages[1].role == "system" and str(messages[1].content).startswith(MARQUEUR_RESUME)
    assert "[ ] Tests" in str(messages[1].content), "la liste de tâches est réinjectée"
    assert messages[2] is demande, "la VRAIE demande reste intacte, pas la relance"
    assert messages[3].role == "assistant" and messages[-1].content == "dernière sortie"
    assert sum(len(m.content) for m in messages if isinstance(m.content, str)) < 700


def test_une_seconde_compaction_englobe_la_premiere(faux: _FauxSuperviseur) -> None:
    messages = _tache(10)
    etat = demarrer(messages)
    asyncio.run(compacter_si_besoin(messages, etat, etape_terminee=False))
    messages.extend(_tache(10)[2:])
    asyncio.run(compacter_si_besoin(messages, etat, etape_terminee=False))
    assert "API faite" in faux.precedents[-1], "le résumé précédent est redonné à intégrer"
    assert sum(1 for m in messages if str(m.content).startswith(MARQUEUR_RESUME)) == 1
    assert etat.compactions == 2


def test_fin_d_etape_compacte_plus_tot(faux: _FauxSuperviseur) -> None:
    messages = _tache(6)  # ~710 tokens : au-delà de l'étape (700), en deçà du dur (800)
    assert asyncio.run(compacter_si_besoin(list(messages), demarrer(messages), etape_terminee=False)) is None
    assert asyncio.run(compacter_si_besoin(messages, demarrer(messages), etape_terminee=True)) is not None


def test_les_reflexions_passees_sont_retirees_les_actes_restent() -> None:
    from backend.inference.harnais_outils import sans_reflexion_passee

    messages = [MessageChat(role="user", content="go"),
                MessageChat(role="assistant", content="<think>je réfléchis longuement</think>J'écris main.py."),
                MessageChat(role="tool", content="Écrit « main.py »")]
    nettoyes = sans_reflexion_passee(messages)
    assert nettoyes[1].content == "J'écris main.py." and nettoyes[0] is messages[0] and nettoyes[2] is messages[2]


def _appel(ident: str, nom: str, **arguments: object) -> MessageChat:
    import json

    return MessageChat(role="assistant", content="", tool_calls=[
        {"id": ident, "type": "function", "function": {"name": nom, "arguments": json.dumps(arguments)}}])


def test_fichiers_de_travail_derniere_version_connue() -> None:
    """Chris, 2026-11-10 : un fichier relu n'existe qu'une fois, dans sa dernière version."""
    from backend.inference.fichiers_travail import selection, suivre

    messages = [
        _appel("1", "lire_fichier", chemin="app.py"), MessageChat(role="tool", content="v1", tool_call_id="1"),
        _appel("2", "lire_fichier", chemin="app.py"), MessageChat(role="tool", content="v2 = 1", tool_call_id="2"),
        _appel("3", "modifier_fichier", chemin="app.py", ancien="= 1", nouveau="= 2"),
        MessageChat(role="tool", content="Modifié", tool_call_id="3"),
        _appel("4", "lire_fichier", chemin="vieux.py"), MessageChat(role="tool", content="x" * 500, tool_call_id="4"),
        _appel("5", "ecrire_fichier", chemin="ui.py", contenu="ui"),
        MessageChat(role="tool", content="Écrit", tool_call_id="5"),
        _appel("6", "lire_fichier", chemin="raté.py"), MessageChat(role="tool", content="Échec : absent", tool_call_id="6"),
    ]
    fichiers = suivre(messages)
    assert fichiers["app.py"].rendu() == "### app.py\nv2 = 2" and "raté.py" not in fichiers
    gardes = [f.chemin for f in selection(fichiers, budget=100)]
    assert gardes == ["ui.py", "app.py"], "les plus récents d'abord ; le lointain trop gros saute"
    assert [f.chemin for f in selection(fichiers, budget=1_000, recents="import vieux")][0] == "vieux.py"


def test_compaction_garde_consignes_et_fichiers(faux: _FauxSuperviseur) -> None:
    messages = [MessageChat(role="system", content="SOCLE"), MessageChat(role="user", content="Utilise pnpm."),
                MessageChat(role="assistant", content="ok"), MessageChat(role="user", content="Fais une app todo.")]
    etat = demarrer(messages, projet=True)
    messages += [_appel("1", "lire_fichier", chemin="main.py"),
                 MessageChat(role="tool", content="print('todo')", tool_call_id="1")]
    for i in range(8):
        messages += [MessageChat(role="assistant", content=f"tour {i} " + "a" * 40),
                     MessageChat(role="tool", content=f"sortie {i} " + "s" * 60)]
    assert asyncio.run(compacter_si_besoin(messages, etat, etape_terminee=False)) is not None
    resume = str(messages[1].content)
    assert "- Utilise pnpm." in resume and "### main.py\nprint('todo')" in resume
    assert "CARTE" in faux.systemes[-1], "le résumé d'un projet demande la carte des chemins"
