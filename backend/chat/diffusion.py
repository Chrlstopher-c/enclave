"""Diffusion d'une génération à plusieurs abonnés — pour se RACCROCHER à un flux en cours.

Une génération n'avait qu'une file, lue par le seul client qui l'avait lancée. Changer de conversation
ou de catégorie fermait ce client : la génération continuait côté serveur, mais plus rien ne
permettait de la revoir en direct (2026-10-02). Ici chaque génération publie dans une `Diffusion` :
un nouvel abonné reçoit d'abord le DÉJÀ-PRODUIT (début, texte condensé, compaction), puis la suite.

`put` a la même forme que `asyncio.Queue.put` : la tâche de production n'a pas changé de contrat.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from loguru import logger

from backend.chat.modeles import EvenementFlux, EvenementFragment

_DIFFUSIONS: dict[str, Diffusion] = {}


class Diffusion:
    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self._journal: list[EvenementFlux] = []
        self._abonnes: list[asyncio.Queue[EvenementFlux | None]] = []
        self._finie = False

    async def put(self, evenement: EvenementFlux | None) -> None:
        """Publie un événement à tous les abonnés ; `None` clôt la diffusion."""
        if evenement is None:
            self._finie = True
            liberer(self)
        else:
            self._journal.append(evenement)
        for file in self._abonnes:
            file.put_nowait(evenement)

    def _rejeu(self) -> list[EvenementFlux]:
        """Le déjà-produit, fragments consécutifs fusionnés : un retour ne rejoue pas 5 000 morceaux."""
        rejeu: list[EvenementFlux] = []
        for evenement in self._journal:
            if isinstance(evenement, EvenementFragment) and rejeu and isinstance(rejeu[-1], EvenementFragment):
                rejeu[-1] = EvenementFragment(texte=rejeu[-1].texte + evenement.texte)
            else:
                rejeu.append(evenement)
        return rejeu

    async def abonner(self) -> AsyncIterator[EvenementFlux]:
        """Le déjà-produit, puis la suite en direct, jusqu'à la clôture. Partir ne touche pas la tâche."""
        file: asyncio.Queue[EvenementFlux | None] = asyncio.Queue()
        # Instantané et inscription sans `await` entre les deux : aucun événement ne peut s'y glisser.
        for evenement in self._rejeu():
            file.put_nowait(evenement)
        if self._finie:
            file.put_nowait(None)
        self._abonnes.append(file)
        try:
            while (evenement := await file.get()) is not None:
                yield evenement
        finally:
            if file in self._abonnes:
                self._abonnes.remove(file)


def ouvrir(conversation_id: str) -> Diffusion:
    diffusion = Diffusion(conversation_id)
    _DIFFUSIONS[conversation_id] = diffusion
    return diffusion


def liberer(diffusion: Diffusion) -> None:
    if _DIFFUSIONS.get(diffusion.conversation_id) is diffusion:
        del _DIFFUSIONS[diffusion.conversation_id]


def en_cours(conversation_id: str) -> Diffusion | None:
    """La diffusion vivante de cette conversation, ou `None`."""
    diffusion = _DIFFUSIONS.get(conversation_id)
    if diffusion is not None:
        logger.info("Raccrochage au flux en cours de {}", conversation_id)
    return diffusion


__all__ = ["Diffusion", "en_cours", "liberer", "ouvrir"]
