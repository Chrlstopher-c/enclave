"""Moteur simulé des tests de commandes : jamais le vrai modèle, jamais le relais Haiku."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from backend.chat.port_inference import MessageInference, OccupationContexte


class MoteurSimule:
    """Occupation mesurée au nombre de caractères ; résumé fixe, éventuellement lent."""

    def __init__(self, resume: str | None = "RÉSUMÉ", attente_s: float = 0.0) -> None:
        self.resume = resume
        self.attente_s = attente_s
        self.consignes: list[str] = []

    async def mesurer_occupation(self, messages: Sequence[MessageInference]) -> OccupationContexte:
        tokens = sum(len(m.contenu) for m in messages)
        return OccupationContexte(mesurable=True, contexte_total=100_000, tokens_mesures=tokens,
                                  tokens_libres=100_000 - tokens)

    async def resumer(self, a_resumer: str, precedent: str, langue: str, max_tokens: int,
                      consigne: str = "") -> str | None:
        self.consignes.append(consigne)
        await asyncio.sleep(self.attente_s)
        return self.resume
