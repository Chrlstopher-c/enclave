"""Compaction NON DESTRUCTIVE du contexte : réduire ce qui part AU MOTEUR, jamais l'historique.

La discipline est celle déjà posée dans `backend/inference/harnais_outils.py` : ce que l'utilisateur
voit et ce qui est enregistré en base ne sont JAMAIS touchés. Ici on ne supprime rien — on remplace,
dans le seul flux envoyé au moteur, les tours anciens par un RÉSUMÉ, quand la fenêtre approche de la
saturation. La base garde tout ; l'API rend tout ; la balise dit à l'humain « à partir d'ici, le
modèle relit ce résumé au lieu des N messages précédents ».

Ce module sépare deux responsabilités :

- la DÉCISION (seuil, point de coupe, assemblage) — pure, testable sans DB ni moteur : elle ne
  connaît que des messages, des nombres de tokens et un résumé antérieur ;
- l'ORCHESTRATION (`preparer_compaction`) — qui appelle le port d'inférence pour mesurer et résumer.
  La persistance en base et l'émission dans le flux SSE restent chez l'appelant (`generation.py`),
  qui seul possède la transaction du message et la file d'événements.

Modèle cumulatif : une nouvelle compaction ENGLOBE le résumé de la précédente. Le résumé antérieur
fait partie de ce qu'on redonne à résumer, il n'est donc jamais oublié — il est réécrit en plus dense
avec les tours qui se sont ajoutés depuis.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import NamedTuple

from loguru import logger

from backend.chat.modeles import InfoCompaction
from backend.chat.port_inference import MessageInference, MoteurGeneration, OccupationContexte
from backend.core import maintenant
from backend.core.politique_compaction import budget_queue, decider

# Seuils et budget de queue : la règle de Quart, commune à `chat` (ici, au départ d'un message) et à
# `inference` (dans la boucle d'outils) — `backend.core.politique_compaction`. Un nouveau message de
# l'utilisateur suit un tour TERMINÉ : c'est une fin d'étape, le seuil d'étape s'applique.

# On garde toujours au moins ce nombre de messages récents intacts : le dernier échange en cours ne
# doit jamais partir dans le résumé, sous peine de résumer la question à laquelle le modèle répond.
GARDER_MINIMUM = 2

# Plafond du résumé, en fraction de la fenêtre : un résumé qui remplirait lui-même la fenêtre n'aurait
# rien compacté. Borné aussi par un plancher pour rester utile sur une petite fenêtre.
FRACTION_MAX_RESUME = 0.25
RESUME_MAX_TOKENS_PLANCHER = 256

# En-tête du message de résumé injecté dans le flux moteur. Rôle `system` : ce n'est pas un tour de
# dialogue, c'est un état que le modèle doit garder présent. Placé après le socle d'outils.
ENTETE_RESUME = "[RÉSUMÉ DES ÉCHANGES PRÉCÉDENTS — le modèle relit ceci à la place des tours ci-dessus]"


class MessageAncre(NamedTuple):
    """Un message d'historique et son identité réelle en base.

    Le port strippe les identifiants (`MessageInference` n'en porte pas), mais la compaction en a
    besoin : le point de coupe doit se dire en identité de message pour survivre à un rechargement et
    à un changement de branche. On transporte donc les deux côte à côte, le temps de décider.
    """

    id: str
    message: MessageInference


class ResultatCompaction(NamedTuple):
    """Ce que l'orchestration rend : les messages à envoyer au moteur, et la balise si compaction."""

    messages: list[MessageInference]
    info: InfoCompaction | None


def depasse_seuil(occupation: OccupationContexte) -> bool:
    """Vrai quand l'occupation MESURÉE franchit le seuil d'étape. Une mesure absente ne déclenche jamais."""
    if not occupation.mesurable:
        return False
    if occupation.contexte_total is None or occupation.tokens_mesures is None:
        return False
    return decider(occupation.tokens_mesures, occupation.contexte_total, etape_terminee=True) is not None


def _message_resume(resume: str) -> MessageInference:
    """Le résumé, sous la forme d'un message système injecté dans le flux moteur."""
    return MessageInference(role="system", contenu=f"{ENTETE_RESUME}\n{resume}")


def _index_coupe(ancres: Sequence[MessageAncre], coupe_message_id: str) -> int | None:
    """Position de la coupe dans l'historique, ou `None` si elle n'est pas sur ce chemin.

    `None` arrive légitimement après un changement de branche : la compaction visait un message
    qui n'est plus sur le fil affiché. On l'ignore alors plutôt que de l'appliquer de travers.
    """
    for index, ancre in enumerate(ancres):
        if ancre.id == coupe_message_id:
            return index
    return None


def appliquer(entete: str, ancres: Sequence[MessageAncre], active: InfoCompaction | None) -> list[MessageInference]:
    """Construit ce qui part au moteur : socle + (résumé actif) + messages récents intacts.

    Fonction PURE. Sans compaction active, rend le socle suivi de tout l'historique — donc rien de
    changé par rapport à l'existant. Avec une compaction active dont la coupe est sur ce chemin, les
    messages jusqu'à la coupe (comprise) sont remplacés par le résumé ; ceux d'après partent intacts.
    """
    messages: list[MessageInference] = []
    if entete.strip():
        messages.append(MessageInference(role="system", contenu=entete))
    verbatim: Sequence[MessageAncre] = ancres
    if active is not None:
        index = _index_coupe(ancres, active.coupe_message_id)
        if index is not None:
            messages.append(_message_resume(active.resume))
            verbatim = ancres[index + 1 :]
    messages.extend(ancre.message for ancre in verbatim)
    return messages


def _verbatim_courant(ancres: Sequence[MessageAncre], active: InfoCompaction | None) -> list[MessageAncre]:
    """Les messages encore envoyés MOT POUR MOT au moteur — ceux d'après la coupe active."""
    if active is None:
        return list(ancres)
    index = _index_coupe(ancres, active.coupe_message_id)
    if index is None:
        return list(ancres)
    return list(ancres[index + 1 :])


def _texte_des(ancres: Sequence[MessageAncre]) -> str:
    """Rend en texte les messages à résumer, rôle en tête — le matériau brut donné au résumeur."""
    return "\n\n".join(f"{ancre.message.role} : {ancre.message.contenu}" for ancre in ancres)


async def choisir_nb_gardes(
    n: int,
    mesurer_tail: Callable[[int], Awaitable[int | None]],
    budget_tokens: int,
) -> int:
    """Combien de messages récents garder intacts pour ramener la queue sous `budget_tokens`.

    Recherche dichotomique du PLUS GRAND nombre de messages de queue dont l'occupation tient dans le
    budget, plancher `GARDER_MINIMUM`. L'occupation d'une queue croît avec sa taille : la monotonie
    justifie la dichotomie. `mesurer_tail(k)` rend les tokens de la queue des `k` derniers messages
    (socle inclus par l'appelant), ou `None` si la mesure est indisponible — auquel cas on garde le
    strict minimum, la seule option prudente quand on ne sait pas.
    """
    if n <= GARDER_MINIMUM:
        return n
    bas, haut, meilleur = GARDER_MINIMUM, n, GARDER_MINIMUM
    # Borne d'itérations explicite : une dichotomie sur `n` éléments converge en log2(n) tours, la
    # garde évite toute boucle infinie si `mesurer_tail` renvoyait des valeurs non monotones.
    for _ in range(n.bit_length() + 2):
        if bas > haut:
            break
        milieu = (bas + haut) // 2
        tokens = await mesurer_tail(milieu)
        if tokens is None:
            return GARDER_MINIMUM
        if tokens <= budget_tokens:
            meilleur, bas = milieu, milieu + 1
        else:
            haut = milieu - 1
    return meilleur


async def preparer_compaction(
    moteur: MoteurGeneration,
    entete: str,
    ancres: Sequence[MessageAncre],
    active: InfoCompaction | None,
    *,
    conversation_id: str,
    message_id: str,
    langue: str = "",
) -> ResultatCompaction:
    """Applique une compaction existante, mesure, et en déclenche une nouvelle si le seuil est franchi.

    Rend TOUJOURS les messages à envoyer au moteur (au minimum : socle + historique intact). `info`
    n'est non nul que si une NOUVELLE compaction a été produite ce tour — c'est elle que l'appelant
    persiste et émet. Toute impossibilité (mesure absente, résumé en échec, rien à replier) laisse la
    génération partir sur le contexte courant, jamais tronqué en douce.
    """
    courant = appliquer(entete, ancres, active)
    occupation = await moteur.mesurer_occupation(courant)
    if not depasse_seuil(occupation):
        return ResultatCompaction(messages=courant, info=None)

    contexte_total = occupation.contexte_total or 0
    tokens_avant = occupation.tokens_mesures or 0
    verbatim = _verbatim_courant(ancres, active)
    budget = budget_queue(contexte_total)

    async def mesurer_tail(k: int) -> int | None:
        essai = appliquer(entete, verbatim[len(verbatim) - k :], None)
        mesure = await moteur.mesurer_occupation(essai)
        return mesure.tokens_mesures if mesure.mesurable else None

    nb_gardes = await choisir_nb_gardes(len(verbatim), mesurer_tail, budget)
    replies = verbatim[: len(verbatim) - nb_gardes]
    if not replies and active is None:
        logger.info("Compaction non applicable : rien à replier sous la queue minimale.")
        return ResultatCompaction(messages=courant, info=None)

    resume = await moteur.resumer(
        _texte_des(replies),
        active.resume if active is not None else "",
        langue,
        max(RESUME_MAX_TOKENS_PLANCHER, int(FRACTION_MAX_RESUME * contexte_total)),
    )
    if resume is None:
        logger.warning("Résumé de compaction indisponible : génération sur contexte courant.")
        return ResultatCompaction(messages=courant, info=None)

    coupe_id = replies[-1].id if replies else _coupe_active(active)
    if coupe_id is None:
        return ResultatCompaction(messages=courant, info=None)
    nb_total = (active.nb_messages_resumes if active is not None else 0) + len(replies)
    info = InfoCompaction(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        message_id=message_id,
        coupe_message_id=coupe_id,
        nb_messages_resumes=nb_total,
        tokens_avant=tokens_avant,
        tokens_apres=0,
        contexte_total=contexte_total,
        resume=resume,
        cree_le=maintenant(),
    )
    reduits = appliquer(entete, ancres, info)
    apres = await moteur.mesurer_occupation(reduits)
    tokens_apres = apres.tokens_mesures if apres.mesurable and apres.tokens_mesures is not None else tokens_avant
    info = info.model_copy(update={"tokens_apres": tokens_apres})
    logger.info(
        "Compaction : {} messages repliés, occupation {} → {} / {} tokens.",
        len(replies), tokens_avant, tokens_apres, contexte_total,
    )
    return ResultatCompaction(messages=reduits, info=info)


def _coupe_active(active: InfoCompaction | None) -> str | None:
    """Point de coupe conservé quand on re-résume sans replier de nouveau message réel."""
    return active.coupe_message_id if active is not None else None
