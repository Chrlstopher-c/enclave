"""L'activité en direct est un ÉTAT : un client qui se reconnecte n'en reçoit que la dernière."""

from __future__ import annotations

import asyncio

from backend.chat import diffusion
from backend.chat.adaptation_inference import normaliser_element
from backend.chat.modeles import EvenementActivite, EvenementFragment
from backend.chat.port_inference import ActiviteGeneration


def test_le_moteur_relaie_l_activite_telle_quelle() -> None:
    element = normaliser_element({"activite": {"phase": "outil", "tokens_par_seconde": 46.0}})
    assert isinstance(element, ActiviteGeneration) and element.activite["phase"] == "outil"


def test_le_rejeu_garde_le_texte_entier_et_la_derniere_activite() -> None:
    async def jouer() -> list[object]:
        flux = diffusion.Diffusion("c-activite")
        for evenement in (EvenementFragment(texte="Bon"), EvenementActivite(activite={"tokens": 1}),
                          EvenementFragment(texte="jour"), EvenementActivite(activite={"tokens": 2}),
                          EvenementActivite(activite={"tokens": 3})):
            await flux.put(evenement)
        await flux.put(None)
        return [e async for e in flux.abonner()]

    rejeu = asyncio.run(jouer())
    fragments = [e for e in rejeu if isinstance(e, EvenementFragment)]
    activites = [e for e in rejeu if isinstance(e, EvenementActivite)]
    assert "".join(f.texte for f in fragments) == "Bonjour"
    assert [a.activite["tokens"] for a in activites] == [3]
