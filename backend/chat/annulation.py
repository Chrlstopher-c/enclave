"""Registre des générations en cours — une seule par conversation, annulable à tout moment.

Pourquoi un registre plutôt qu'un simple drapeau : la route qui annule et la route qui streame sont
deux requêtes HTTP distinctes. Il faut un état partagé au niveau du processus pour que l'une puisse
atteindre l'autre.

Pourquoi aucun verrou : toutes les fonctions de ce module sont synchrones et ne contiennent aucun
`await`. Sur la boucle d'événements unique d'uvicorn, il n'existe donc aucun point d'entrelacement
entre le test d'occupation et l'insertion. Ajouter un verrou donnerait l'illusion d'une protection
contre le multi-processus, qu'aucun verrou en mémoire ne peut fournir de toute façon.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from loguru import logger

from backend.chat.erreurs import GenerationDejaEnCours

# Une réservation posée par la route mais jamais consommée (client parti entre la requête et la
# lecture du flux) bloquerait la conversation indéfiniment. Passé ce délai, elle est reprise.
DELAI_RESERVATION_ABANDONNEE_S = 30.0
# Attente maximale d'un arrêt : de quoi fermer le flux et écrire le partiel, pas plus.
DELAI_ARRET_S = 15.0


@dataclass(slots=True)
class GenerationActive:
    """Génération réservée ou en cours sur une conversation."""

    conversation_id: str
    message_id: str
    reservee_le: float
    flux_demarre: bool = False
    arret: asyncio.Event = field(default_factory=asyncio.Event)
    # Posé APRÈS la persistance du message (même partiel) : c'est ce qu'attend un arrêt pour que
    # l'interface relise un fil où le travail déjà fait figure. Sans lui, la relecture partait avant
    # l'écriture et l'écran se vidait jusqu'au rafraîchissement suivant (2026-10-02).
    terminee: asyncio.Event = field(default_factory=asyncio.Event)


# État partagé du processus : les générations en cours, indexées par conversation.
_actives: dict[str, GenerationActive] = {}


def reserver(conversation_id: str, message_id: str) -> GenerationActive:
    """Réserve la conversation pour une génération. Lève si une génération y est déjà vivante."""
    existante = _actives.get(conversation_id)
    if existante is not None and not _est_abandonnee(existante):
        raise GenerationDejaEnCours(f"Une génération est déjà en cours sur la conversation {conversation_id}.")
    if existante is not None:
        logger.warning(
            "Réservation abandonnée reprise sur {} (posée il y a {:.0f} s)",
            conversation_id,
            time.monotonic() - existante.reservee_le,
        )
        existante.arret.set()

    generation = GenerationActive(
        conversation_id=conversation_id,
        message_id=message_id,
        reservee_le=time.monotonic(),
    )
    _actives[conversation_id] = generation
    return generation


def _est_abandonnee(generation: GenerationActive) -> bool:
    """Une réservation dont le flux n'a jamais démarré et qui a dépassé le délai est perdue."""
    if generation.flux_demarre:
        return False
    return (time.monotonic() - generation.reservee_le) > DELAI_RESERVATION_ABANDONNEE_S


def marquer_demarree(generation: GenerationActive) -> None:
    """Signale que le client consomme effectivement le flux : la réservation n'est plus reprenable."""
    generation.flux_demarre = True


def liberer(generation: GenerationActive) -> None:
    """Libère la conversation, sans écraser une génération plus récente qui aurait pris la place."""
    courante = _actives.get(generation.conversation_id)
    if courante is generation:
        del _actives[generation.conversation_id]


def annuler(conversation_id: str) -> bool:
    """Demande l'arrêt de la génération en cours. Retourne `False` s'il n'y en a pas."""
    generation = _actives.get(conversation_id)
    if generation is None:
        return False
    generation.arret.set()
    logger.info("Annulation demandée sur la conversation {}", conversation_id)
    return True


async def annuler_et_attendre(conversation_id: str, delai_s: float = DELAI_ARRET_S) -> bool:
    """Arrête la génération et attend qu'elle ait persisté ce qu'elle a produit (borné par `delai_s`)."""
    generation = _actives.get(conversation_id)
    if not annuler(conversation_id) or generation is None:
        return False
    try:
        await asyncio.wait_for(generation.terminee.wait(), timeout=delai_s)
    except asyncio.TimeoutError:
        logger.warning("Arrêt de {} : génération pas terminée après {:.0f} s.", conversation_id, delai_s)
    return True


def est_active(conversation_id: str) -> bool:
    """Indique si une génération est réservée ou en cours sur cette conversation."""
    return conversation_id in _actives


def conversations_actives() -> list[str]:
    """Conversations occupées à cet instant — utile au diagnostic et aux tests."""
    return sorted(_actives)


def reinitialiser() -> None:
    """Vide le registre — réservé aux tests, pour qu'un cas n'hérite pas de l'état du précédent."""
    for generation in list(_actives.values()):
        generation.arret.set()
    _actives.clear()
