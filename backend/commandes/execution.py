"""Exécution des commandes du chat : une tâche serveur par commande, indépendante de la requête qui la lance.

Une commande RÉSERVE sa conversation comme une génération (`annulation.reserver`) : generer, rejouer,
editer et l'effacement répondent 409 tant qu'elle tourne. Sa progression est publiée dans la `Diffusion`
de la conversation, donc rejouée à quiconque se raccroche ; personne n'écoutant, la tâche va au bout quand même.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from loguru import logger

from backend.chat import annulation, depot, diffusion
from backend.chat.annulation import GenerationActive
from backend.chat.compaction_manuelle import produire_compaction
from backend.chat.diffusion import Diffusion
from backend.chat.erreurs import BrancheInvalide, GenerationDejaEnCours
from backend.chat.modeles import EvenementCommande, EvenementCompaction, InfoCompaction
from backend.commandes.catalogue import CommandeInvalide
from backend.commandes.progression import EtatCommande, battements
from backend.core import EchoHubError

# Référence forte : un asyncio.Task sans référence peut être ramassé en cours d'exécution.
_TACHES: set[asyncio.Task[Any]] = set()


@dataclass(frozen=True)
class Lancement:
    """Ce que la route rend : l'identifiant, la tâche (absente pour `clear`, synchrone) et l'effacement."""

    commande_id: str
    nom: str
    tache: asyncio.Task[Any] | None = None
    effacement: dict[str, Any] | None = None


async def lancer(conversation_id: str, nom: str, arguments: str = "") -> Lancement:
    """Démarre une commande. Lève avant toute écriture si elle est refusée (409, 422)."""
    if nom == "clear":
        return _effacer(conversation_id, arguments)
    if nom == "compact":
        commande_id, tache = await _demarrer_compaction(conversation_id, arguments)
        return Lancement(commande_id=commande_id, nom=nom, tache=tache)
    raise CommandeInvalide(f"Commande non exécutable : /{nom}")


async def compacter_et_attendre(conversation_id: str, instructions: str = "") -> InfoCompaction:
    """`POST …/compacter` (mobile) : même commande que `/compact`, mais la requête attend sa fin.

    `shield` : si la requête HTTP tombe, la compaction, elle, continue.
    """
    _, tache = await _demarrer_compaction(conversation_id, instructions)
    return await asyncio.shield(tache)


def _effacer(conversation_id: str, arguments: str) -> Lancement:
    if arguments.strip():
        raise CommandeInvalide("/clear ne prend pas d'arguments.")
    if annulation.est_active(conversation_id):
        raise GenerationDejaEnCours("Une génération ou une commande est en cours sur cette conversation.")
    if not depot.lister_messages(conversation_id):
        raise BrancheInvalide("Rien à effacer : la conversation est vide.")
    from backend.chat.effacement import effacer  # import paresseux : l'effacement vit dans le domaine `chat`

    info = effacer(conversation_id)
    logger.info("Commande /clear sur {} : ancre {}", conversation_id, info.model_dump(mode="json")["ancre_message_id"])
    return Lancement(commande_id=str(uuid.uuid4()), nom="clear", effacement=info.model_dump(mode="json"))


async def _demarrer_compaction(conversation_id: str, instructions: str) -> tuple[str, asyncio.Task[InfoCompaction]]:
    if not depot.lister_messages(conversation_id):
        raise BrancheInvalide("Rien à compacter : la conversation est vide.")
    commande_id = str(uuid.uuid4())
    generation = annulation.reserver(conversation_id, commande_id)
    annulation.marquer_demarree(generation)
    publication = diffusion.ouvrir(conversation_id)
    etat = EtatCommande(id=commande_id, nom="compact")
    await publication.put(_evenement(etat))
    tache = asyncio.create_task(_executer(etat, publication, generation, conversation_id, instructions))
    _garder(tache)
    return commande_id, tache


async def _executer(
    etat: EtatCommande, publication: Diffusion, generation: GenerationActive, conversation_id: str,
    instructions: str,
) -> InfoCompaction:
    try:
        info = await _compacter_en_direct(etat, publication, conversation_id, instructions)
        etat.terminer()
        await publication.put(EvenementCompaction(compaction=info))
        await publication.put(_evenement(etat))
        return info
    except Exception as exc:  # noqa: BLE001 — l'échec est publié tel quel, puis re-levé pour qui attend la tâche
        etat.echouer(_message(exc))
        logger.warning("Commande /compact échouée sur {} : {}", conversation_id, exc)
        await publication.put(_evenement(etat))
        raise
    finally:
        annulation.liberer(generation)
        generation.terminee.set()
        await publication.put(None)


async def _compacter_en_direct(
    etat: EtatCommande, publication: Diffusion, conversation_id: str, instructions: str,
) -> InfoCompaction:
    async def suivre(details: dict[str, Any]) -> None:
        etat.progression.appliquer(details)
        if "etape" in details:
            await publication.put(_evenement(etat))

    tache = asyncio.create_task(produire_compaction(conversation_id, instructions, suivre))
    async for _ in battements(tache):
        await publication.put(_evenement(etat))
    return tache.result()


def _evenement(etat: EtatCommande) -> EvenementCommande:
    return EvenementCommande(commande=etat.snapshot())


def _message(exc: Exception) -> str:
    if isinstance(exc, EchoHubError):
        return str(exc)
    return f"Erreur interne : {exc}"


def _garder(tache: asyncio.Task[Any]) -> None:
    _TACHES.add(tache)
    tache.add_done_callback(_relacher)


def _relacher(tache: asyncio.Task[Any]) -> None:
    _TACHES.discard(tache)
    if not tache.cancelled():
        tache.exception()  # marque l'erreur comme lue : elle est déjà publiée et journalisée
