"""Résumé de compaction — le modèle chargé résume ses propres tours anciens.

Ce module ne DÉCIDE rien : il ne dit ni quand compacter, ni où couper (c'est le domaine `chat`, qui
possède la fenêtre de contexte et l'historique). Il fait une seule chose : demander au modèle prêt
un résumé cumulatif, orienté reprise de tâche, et rendre son texte visible — ou `None` si aucun
modèle n'est prêt. C'est le pendant, pour la compaction, de ce que `reprise.py` est à la continuation.

Le résumé sert un AGENT, pas un lecteur : il préserve l'objectif, l'état courant, les fichiers
touchés, les décisions et ce qui reste à faire. Un résumé « littéraire » perdrait exactement ce qui
permet à une session longue de ne pas oublier sa tâche.
"""

from __future__ import annotations

from loguru import logger

from backend.inference.engines_adapters import (
    MessageChat,
    OptionsGeneration,
    superviseur,
)
from backend.inference.engines_adapters.contrat import separer_raisonnement

# Température basse : un résumé est une restitution fidèle, pas une génération créative. On veut la
# même tâche décrite deux fois de la même façon, pas une reformulation qui dérive à chaque compaction.
_TEMPERATURE_RESUME = 0.3

# Même consigne que la compaction de Quart (« Conserve … Jette … ») : un agent reprend sa tâche sur ce
# résumé, il doit y trouver ce qui ne se relit pas ailleurs — et rien de ce qui est déjà sur disque.
PROMPT_RESUME_SYSTEME = (
    "Tu es un compacteur de contexte pour un agent autonome. On te donne un extrait de conversation, "
    "éventuellement précédé d'un résumé antérieur à INTÉGRER. Produis un unique RÉSUMÉ CUMULATIF, "
    "dense et fidèle, rédigé dans la MÊME LANGUE que la conversation. N'ajoute aucun commentaire, ne "
    "t'adresse à personne, n'annonce pas que tu résumes : écris seulement le résumé. Structure-le "
    "pour qu'un agent reprenne la tâche sans relire les messages :\n"
    "- OBJECTIF : le but de la tâche, tel que l'utilisateur l'a demandé.\n"
    "- ÉTAT : l'étape en cours et les suivantes ; la liste de tâches si elle existe, avec l'état de chacune.\n"
    "- DÉCISIONS : les choix faits et POURQUOI.\n"
    "- FICHIERS : fichiers créés ou modifiés, et leur rôle (pas leur contenu).\n"
    "- COMMANDES : les commandes de build, de test et de lancement qui MARCHENT, telles quelles ; "
    "les serveurs lancés et leurs ports ; l'état git s'il y en a un.\n"
    "- PIÈGES : les erreurs rencontrées, leur cause et leur correctif.\n"
    "JETTE : les sorties d'outils (garde-en seulement la conclusion), les explorations closes, et le "
    "code déjà écrit — il est sur disque, l'agent le relira s'il en a besoin.\n"
    "Si un résumé antérieur est fourni, ENGLOBE-le : n'oublie rien de ce qu'il portait."
)

_ENTETE_RESUME_ANTERIEUR = "[RÉSUMÉ ANTÉRIEUR À INTÉGRER]"
_ENTETE_ECHANGES = "[ÉCHANGES À RÉSUMER]"


def construire_messages_resume(a_resumer: str, resume_precedent: str) -> list[MessageChat]:
    """Prompt de résumé : consigne système + le matériau à condenser, résumé antérieur en tête."""
    corps = ""
    if resume_precedent.strip():
        corps += f"{_ENTETE_RESUME_ANTERIEUR}\n{resume_precedent.strip()}\n\n"
    corps += f"{_ENTETE_ECHANGES}\n{a_resumer.strip()}"
    return [
        MessageChat(role="system", content=PROMPT_RESUME_SYSTEME),
        MessageChat(role="user", content=corps),
    ]


async def produire_resume(
    a_resumer: str, resume_precedent: str, langue: str, max_tokens: int
) -> str | None:
    """Demande au modèle chargé un résumé cumulatif, ou `None` si rien ne peut être produit.

    `langue` est indicatif — la consigne demande déjà « la langue de la conversation » — mais on
    l'ajoute au besoin pour lever toute ambiguïté sur un extrait court. Le raisonnement éventuel du
    modèle (`<think>`) est retiré : la balise doit montrer le résumé, pas le cheminement qui y mène.
    """
    if not a_resumer.strip() and not resume_precedent.strip():
        return None
    messages = construire_messages_resume(a_resumer, resume_precedent)
    if langue.strip():
        messages[0] = MessageChat(
            role="system",
            content=f"{PROMPT_RESUME_SYSTEME}\nLangue attendue du résumé : {langue.strip()}.",
        )
    options = OptionsGeneration(temperature=_TEMPERATURE_RESUME, max_tokens=max_tokens)
    morceaux: list[str] = []
    try:
        async for morceau in superviseur.generer(messages, options, None):
            if morceau.type == "token" and morceau.contenu:
                morceaux.append(morceau.contenu)
            elif morceau.type == "erreur":
                logger.error("Résumé de compaction interrompu par le moteur : {}", morceau.contenu)
                return None
    except Exception as exc:  # noqa: BLE001 — un résumé absent annule la compaction, il ne casse rien
        logger.warning("Résumé de compaction impossible ({}) : compaction abandonnée.", exc)
        return None
    visible, _ = separer_raisonnement("".join(morceaux))
    texte = visible.strip()
    if not texte:
        logger.warning("Le modèle n'a produit aucun résumé exploitable : compaction abandonnée.")
        return None
    return texte
