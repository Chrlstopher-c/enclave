"""Arrêter pendant un long appel d'outil : le travail déjà produit est enregistré AVANT la réponse.

Mesuré le 2026-10-02 : l'arrêt répondait tout de suite, l'interface relisait un fil où la réponse
n'était pas encore écrite, et l'écran se vidait jusqu'au rafraîchissement suivant. Et pendant un
appel d'outil (aucun token), l'arrêt n'était vu qu'au token suivant — jusqu'à 10 minutes.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest

from backend.chat import annulation, depot, generation, port_inference
from backend.chat.modeles import DemandeGeneration, ResumeConversation
from backend.chat.port_inference import ElementFlux, FragmentTexte, RequeteGeneration


class MoteurBloque:
    """Écrit un premier tour, puis reste muet comme pendant une commande d'outil de 10 minutes."""

    def generer(self, requete: RequeteGeneration) -> AsyncIterator[ElementFlux]:
        return self._flux()

    async def _flux(self) -> AsyncIterator[ElementFlux]:
        yield FragmentTexte(texte="J'ai écrit main.py et lancé les tests. ")
        await asyncio.sleep(600)
        yield FragmentTexte(texte="jamais atteint")


@pytest.fixture
def moteur_bloque() -> Iterator[MoteurBloque]:
    factice = MoteurBloque()
    port_inference.definir_moteur(factice)
    yield factice
    port_inference.reinitialiser_moteur()


def test_arret_pendant_un_outil_enregistre_le_partiel_avant_de_repondre(
    conversation: ResumeConversation, moteur_bloque: MoteurBloque
) -> None:
    async def scenario() -> tuple[bool, float]:
        flux = generation.diffuser(generation.preparer(conversation.id, DemandeGeneration(contenu="code")))
        async for evenement in flux:
            if getattr(evenement, "type", "") == "fragment":
                break
        debut = asyncio.get_running_loop().time()
        annulee = await annulation.annuler_et_attendre(conversation.id, delai_s=5)
        duree = asyncio.get_running_loop().time() - debut
        await flux.aclose()
        return annulee, duree

    annulee, duree = asyncio.run(scenario())
    assert annulee and duree < 3, "l'arrêt est vu pendant l'attente, sans attendre l'outil"
    reponses = [m for m in depot.lister_messages(conversation.id) if m.role == "assistant"]
    assert reponses and reponses[-1].contenu == "J'ai écrit main.py et lancé les tests. "
    assert reponses[-1].interrompu, "le partiel est enregistré, marqué interrompu, AVANT la réponse"
