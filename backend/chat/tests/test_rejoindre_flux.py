"""Se raccrocher à une génération en cours : le déjà-produit d'abord, puis le direct, jusqu'à la fin."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest

from backend.chat import diffusion, generation, port_inference
from backend.chat.modeles import DemandeGeneration, ResumeConversation
from backend.chat.port_inference import ElementFlux, FragmentTexte, RequeteGeneration


class MoteurPoli:
    """Six fragments, avec une vraie pause entre chacun pour laisser le temps de partir et revenir."""

    def generer(self, requete: RequeteGeneration) -> AsyncIterator[ElementFlux]:
        return self._flux()

    async def _flux(self) -> AsyncIterator[ElementFlux]:
        for i in range(6):
            await asyncio.sleep(0.02)
            yield FragmentTexte(texte=f"m{i} ")


@pytest.fixture
def moteur() -> Iterator[MoteurPoli]:
    factice = MoteurPoli()
    port_inference.definir_moteur(factice)
    yield factice
    port_inference.reinitialiser_moteur()


def test_un_client_qui_revient_voit_le_deja_produit_puis_la_suite(
    conversation: ResumeConversation, moteur: MoteurPoli
) -> None:
    async def scenario() -> list[str]:
        flux = generation.diffuser(generation.preparer(conversation.id, DemandeGeneration(contenu="go")))
        recus = 0
        async for evenement in flux:
            recus += evenement.type == "fragment"
            if recus == 2:
                break
        await flux.aclose()  # le client change de conversation : la génération continue
        publication = diffusion.en_cours(conversation.id)
        assert publication is not None
        return [f"{e.type}:{getattr(e, 'texte', '')}" async for e in publication.abonner()]

    types = asyncio.run(scenario())
    assert types[0].startswith("debut")
    assert types[1] == "fragment:m0 m1 ", "le déjà-produit arrive condensé en un seul fragment"
    assert "fragment:m5 " in types and types[-1].startswith("fin")
    assert diffusion.en_cours(conversation.id) is None, "la diffusion se libère à la fin"
