"""Rejoue la photo de Chris du 2026-11-10 : le modèle relit sans fin la même plage d'un fichier.

Le modèle factice demande TOUJOURS `lire_fichier(ligne_debut=439)` avec la même phrase ; l'outil rend
toujours la même sortie courte. Avec le harnais FORGE (prolongations illimitées), rien n'arrêtait la
boucle. Elle doit maintenant s'arrêter d'elle-même et finir sur une réponse sans outil.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import backend.inference as domaine_inference
from backend.chat.modeles import ParametresEchantillonnage
from backend.chat.port_inference import MessageInference, RequeteGeneration
from backend.inference import MoteurChat
from backend.inference.engines_adapters.contrat import MessageChat, MorceauGeneration, OptionsGeneration
from backend.inference.memoire_travail import CONSIGNE_BOUCLE, REDITES_ARRET
from backend.outils import registre
from backend.outils.contrat import ContexteExecution, DescriptionOutil, Outil

PHRASE = "The file ends at line 438, so I need to read from line 439."
APPEL = ("<function=lire_fichier>\n<parameter=chemin>\nt.py\n</parameter>\n"
         "<parameter=ligne_debut>\n439\n</parameter>\n</function>")


class _ModeleQuiRelit:
    def __init__(self) -> None:
        self.tours = 0
        self.derniers: list[MessageChat] = []

    def generer(self, messages: Sequence[MessageChat], options: OptionsGeneration,
                outils: Sequence[dict[str, Any]] | None = None) -> AsyncIterator[MorceauGeneration]:
        self.tours += 1
        self.derniers = list(messages)
        return self._flux(outils is not None)

    async def _flux(self, avec_outils: bool) -> AsyncIterator[MorceauGeneration]:
        yield MorceauGeneration(type="token", contenu=f"{PHRASE}{APPEL}" if avec_outils else "Bilan.")


def _jouer(monkeypatch: Any) -> tuple[_ModeleQuiRelit, list[dict[str, Any]]]:
    executions: list[dict[str, Any]] = []

    async def lire(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
        executions.append(arguments)
        return "[lignes 439-438 sur 438]"

    outil = Outil(description=DescriptionOutil(nom="lire_fichier", description="test",
                                               parametres={"type": "object", "properties": {}}), executer=lire)
    monkeypatch.setitem(registre._OUTILS, "lire_fichier", outil)
    modele = _ModeleQuiRelit()
    monkeypatch.setattr(domaine_inference, "superviseur", modele)

    async def consommer() -> None:
        requete = RequeteGeneration(messages=[MessageInference(role="user", contenu="continue")],
                                    parametres=ParametresEchantillonnage(), conversation_id="boucle")
        async for _ in MoteurChat().generer(requete):
            pass

    asyncio.run(consommer())
    return modele, executions


def test_la_boucle_de_relecture_s_arrete_d_elle_meme(monkeypatch: Any) -> None:
    modele, executions = _jouer(monkeypatch)
    assert len(executions) == REDITES_ARRET + 1, "la première lecture, puis les redites jusqu'au seuil"
    assert any(str(m.content) == CONSIGNE_BOUCLE for m in modele.derniers), "clôture motivée"
