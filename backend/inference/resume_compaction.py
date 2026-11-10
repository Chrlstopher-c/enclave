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
    "- DIRECTIVES ACTIVES : les consignes de l'utilisateur ENCORE VALABLES pour le travail en cours (outils "
    "imposés, conventions, interdits, préférences, choix validés), condensées une par ligne. Omets celles qui "
    "sont accomplies ou caduques : elles pollueraient le contexte.\n"
    "- ÉTAT : l'étape en cours et les suivantes ; la liste de tâches si elle existe, avec l'état de chacune.\n"
    "- DÉCISIONS : les choix faits et POURQUOI.\n"
    "- FICHIERS : fichiers lus, créés ou modifiés, avec pour chacun ce qu'on y a appris ou changé "
    "(fonctions clés, numéros de ligne utiles, taille) — pas leur contenu.\n"
    "- COMMANDES : les commandes de build, de test et de lancement qui MARCHENT, telles quelles ; "
    "les serveurs lancés et leurs ports ; l'état git s'il y en a un.\n"
    "- PIÈGES : les erreurs rencontrées, leur cause et leur correctif.\n"
    "JETTE : les sorties brutes des outils (garde la conclusion et les faits utiles : noms, lignes, "
    "erreurs), les explorations closes, et le code déjà écrit — il est sur disque. Écris ce qui a été "
    "lu et compris pour que l'agent n'ait PAS à le relire.\n"
    "Si un résumé antérieur est fourni, ENGLOBE-le : n'oublie rien de ce qu'il portait."
)

_ENTETE_RESUME_ANTERIEUR = "[RÉSUMÉ ANTÉRIEUR À INTÉGRER]"
_ENTETE_ECHANGES = "[ÉCHANGES À RÉSUMER]"


# Ce qu'un agent qui CONSTRUIT un projet doit retrouver après compaction (Chris, 2026-11-10) : la carte du
# projet et ses notions, pas le récit de l'exploration.
COMPLEMENT_PROJET = (
    "\nCette tâche construit ou modifie un PROJET. Ajoute :\n"
    "- CARTE : les chemins importants (dossiers, points d'entrée, configuration) et le rôle de chacun.\n"
    "- NOTIONS : les concepts du domaine, les conventions de nommage et les interfaces internes à respecter.\n"
    "N'y mets ni listing complet, ni contenu de fichier : seulement ce qui oriente le travail suivant."
)


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


def _systeme(langue: str, consigne: str, projet: bool) -> str:
    """Consigne du résumeur : la base, la langue, le complément projet, les instructions de /compact."""
    systeme = PROMPT_RESUME_SYSTEME
    if langue.strip():
        systeme += f"\nLangue attendue du résumé : {langue.strip()}."
    if projet:
        systeme += COMPLEMENT_PROJET
    if consigne.strip():
        # Compaction manuelle (`/compact …`) : ce que l'utilisateur demande de garder prime.
        systeme += f"\nINSTRUCTIONS DE L'UTILISATEUR POUR CE RÉSUMÉ, PRIORITAIRES : {consigne.strip()}"
    return systeme


async def produire_resume(
    a_resumer: str, resume_precedent: str, langue: str, max_tokens: int, consigne: str = "",
    projet: bool = False,
) -> str | None:
    """Demande au modèle chargé un résumé cumulatif, ou `None` si rien ne peut être produit.

    `langue` est indicatif — la consigne demande déjà « la langue de la conversation » — mais on
    l'ajoute au besoin pour lever toute ambiguïté sur un extrait court. Le raisonnement éventuel du
    modèle (`<think>`) est retiré : la balise doit montrer le résumé, pas le cheminement qui y mène.
    """
    if not a_resumer.strip() and not resume_precedent.strip():
        return None
    messages = construire_messages_resume(a_resumer, resume_precedent)
    systeme = _systeme(langue, consigne, projet)
    messages[0] = MessageChat(role="system", content=systeme)
    options = OptionsGeneration(temperature=_TEMPERATURE_RESUME, max_tokens=max_tokens, sans_reflexion=True)
    from backend.outils.noms_publics import publier_messages

    morceaux: list[str] = []
    try:
        async for morceau in superviseur.generer(publier_messages(messages), options, None):
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
