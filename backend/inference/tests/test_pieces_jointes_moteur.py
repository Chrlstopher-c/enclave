"""Preuve d'assemblage : une pièce jointe du port `chat` atteint le contenu moteur (plan, 2.2).

Même schéma que `test_contexte_execution_outil.py` : `MoteurChat.generer` (le vrai) est appelé avec
une `RequeteGeneration` réelle, seul le LLM sous-jacent (`superviseur`) est remplacé. Ce qui est
vérifié ici est la traduction `MessageInference.pieces` (chemins, forme du port) -> `MessageChat.content`
(liste de parties, forme du contrat moteur) faite par `_messages_depuis` — AUCUN octet, AUCUN base64
ne doit apparaître à ce stade : seul l'adaptateur llama.cpp encode, plus tard.
"""

from __future__ import annotations

import pytest

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import backend.inference as domaine_inference
from backend.chat.modeles import ParametresEchantillonnage
from backend.chat.port_inference import MessageInference, PieceJointe, RequeteGeneration
from backend.inference import MoteurChat
from backend.inference.engines_adapters.contrat import (
    MessageChat,
    MorceauGeneration,
    OptionsGeneration,
    PartieImageChemin,
    PartieTexte,
)

CONVERSATION_ID = "conversation-multimodale"

@pytest.fixture(autouse=True)
def _harnais_d_origine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ces cas décrivent la conduite d'origine (6 tours puis couperet, sans relance) : ils la figent,
    le défaut étant passé à FORGE (prolongations illimitées, relance des tours muets)."""
    from backend.inference import harnais

    monkeypatch.setattr(harnais, "DEFAUT", harnais.ECHOHUB)



class SuperviseurCapture:
    """Capture les messages reçus par le moteur, sans jamais avoir besoin de GPU ni de GGUF."""

    def __init__(self) -> None:
        self.appels: list[list[MessageChat]] = []

    def generer(
        self,
        messages: Sequence[MessageChat],
        options: OptionsGeneration,
        outils: Sequence[dict[str, Any]] | None = None,
    ) -> AsyncIterator[MorceauGeneration]:
        self.appels.append(list(messages))
        return self._flux()

    async def _flux(self) -> AsyncIterator[MorceauGeneration]:
        yield MorceauGeneration(type="token", contenu="Je ne vois rien de spécial.")


def _consommer(requete: RequeteGeneration) -> None:
    async def lire() -> None:
        moteur = MoteurChat()
        async for _ in moteur.generer(requete):
            pass

    asyncio.run(lire())


def test_une_piece_jointe_devient_une_partie_image_chemin_dans_le_contenu_moteur(
    monkeypatch: Any,
) -> None:
    capture = SuperviseurCapture()
    monkeypatch.setattr(domaine_inference, "superviseur", capture)

    requete = RequeteGeneration(
        messages=[
            MessageInference(
                role="user",
                contenu="Regarde cette photo",
                pieces=[PieceJointe(chemin=Path("/tmp/photo.png"), type_mime="image/png", nom_affiche="photo.png")],
            )
        ],
        parametres=ParametresEchantillonnage(),
        conversation_id=CONVERSATION_ID,
    )

    _consommer(requete)

    assert len(capture.appels) == 1
    message = capture.appels[0][0]
    assert isinstance(message.content, list)
    assert message.content[0] == PartieTexte(text="Regarde cette photo")
    partie_image = message.content[1]
    assert isinstance(partie_image, PartieImageChemin)
    # C'est un CHEMIN, jamais des octets ni du base64 : la preuve littérale de la décision 2.2.2.
    assert partie_image.chemin == "/tmp/photo.png"
    assert partie_image.type_mime == "image/png"
    assert not partie_image.chemin.startswith("data:")


def test_un_message_sans_piece_jointe_garde_un_contenu_texte_simple(monkeypatch: Any) -> None:
    """Non-régression : la forme d'avant ce lot doit rester intacte pour l'écrasante majorité
    des messages, qui n'ont pas de pièce jointe."""
    capture = SuperviseurCapture()
    monkeypatch.setattr(domaine_inference, "superviseur", capture)

    requete = RequeteGeneration(
        messages=[MessageInference(role="user", contenu="Bonjour")],
        parametres=ParametresEchantillonnage(),
        conversation_id=CONVERSATION_ID,
    )

    _consommer(requete)

    message = capture.appels[0][0]
    assert message.content == "Bonjour"
