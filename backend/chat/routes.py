"""Routes HTTP du domaine `chat`.

Le routeur ne porte pas le préfixe `/api` : la couche d'assemblage (`main.py`) le monte, comme pour
les autres domaines, ce qui laisse un seul endroit décider de la forme des URL publiques.

Toutes les routes sont `async`. Les accès SQLite qu'elles font sont synchrones, mais ce sont des
lectures indexées sur un fichier local : leur coût est sans commune mesure avec la génération
elle-même, et les exécuter dans un pool de threads multiplierait les connexions SQLite (une par
thread) pour rien.

Traduction des erreurs : un décorateur unique transforme toute `EchoHubError` en réponse HTTP en
s'appuyant sur `statut_http` et `to_dict()`. Aucune table de correspondance n'est réécrite ici —
c'était la promesse de `core.errors`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
import json

from loguru import logger

from backend.chat import annulation, depot, flux_sse, generation
from backend.chat.compaction_manuelle import compacter_maintenant
from backend.chat.modeles import (
    ActivationBranche,
    ArbreConversation,
    ConversationDetaillee,
    CreationConversation,
    DemandeCompaction,
    DemandeEdition,
    DemandeGeneration,
    DemandeRejeu,
    EtatBranche,
    InfoCompaction,
    MajConversation,
    MajReglages,
    MessageChat,
    ReglagesConversation,
    ResumeConversation,
    OutilDisponible,
    SelectionOutils,
    fusionner_reglages,
)
from backend.core import EchoHubError
from backend.projets import LiaisonProjet, chemin_projet

PREFIXE = "/chat"

routeur = APIRouter(prefix=PREFIXE, tags=["chat"])

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _traduire_erreurs(fonction: Callable[_P, Awaitable[_R]]) -> Callable[_P, Awaitable[_R]]:
    """Convertit les erreurs métier en réponses HTTP, en préservant la signature vue par FastAPI."""

    @wraps(fonction)
    async def enveloppe(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            return await fonction(*args, **kwargs)
        except EchoHubError as exc:
            logger.warning("{} : {}", fonction.__name__, exc)
            raise HTTPException(status_code=exc.statut_http, detail=exc.to_dict()) from exc

    return enveloppe


@routeur.get("/conversations", response_model=list[ResumeConversation])
@_traduire_erreurs
async def lister_conversations(archivees: bool = Query(default=False)) -> list[ResumeConversation]:
    """Liste les conversations, actives par défaut."""
    return depot.lister_conversations(archivees=archivees)


@routeur.post("/conversations", response_model=ResumeConversation, status_code=status.HTTP_201_CREATED)
@_traduire_erreurs
async def creer_conversation(corps: CreationConversation) -> ResumeConversation:
    """Crée une conversation et ses réglages initiaux."""
    return depot.creer_conversation(corps.titre, corps.modele_id, corps.reglages)


@routeur.get("/conversations/{conversation_id}", response_model=ConversationDetaillee)
@_traduire_erreurs
async def lire_conversation(conversation_id: str) -> ConversationDetaillee:
    """Conversation complète : métadonnées, réglages et branche affichée en une réponse.

    `messages` est le chemin actif de l'arbre. Sur une conversation linéaire — toutes celles
    écrites avant les branches — c'est exactement l'historique complet, dans le même ordre.
    """
    conversation = depot.exiger_conversation(conversation_id)
    branche = depot.lire_branche(conversation_id)
    return ConversationDetaillee(
        conversation=conversation,
        reglages=depot.lire_reglages(conversation_id),
        messages=branche.messages,
        feuille_active=branche.feuille_active,
        variantes=branche.variantes,
    )


@routeur.patch("/conversations/{conversation_id}", response_model=ResumeConversation)
@_traduire_erreurs
async def modifier_conversation(conversation_id: str, corps: MajConversation) -> ResumeConversation:
    """Renomme, archive ou change le modèle par défaut d'une conversation."""
    return depot.maj_conversation(conversation_id, corps)


@routeur.delete("/conversations/{conversation_id}")
@_traduire_erreurs
async def supprimer_conversation(conversation_id: str) -> dict[str, bool]:
    """Supprime la conversation, ses messages et ses réglages, après avoir arrêté toute génération."""
    annulation.annuler(conversation_id)
    depot.supprimer_conversation(conversation_id)
    return {"supprimee": True}


@routeur.get("/conversations/{conversation_id}/reglages", response_model=ReglagesConversation)
@_traduire_erreurs
async def lire_reglages(conversation_id: str) -> ReglagesConversation:
    """Prompt système et paramètres d'échantillonnage de la conversation."""
    depot.exiger_conversation(conversation_id)
    return depot.lire_reglages(conversation_id)


@routeur.patch("/conversations/{conversation_id}/reglages", response_model=ReglagesConversation)
@_traduire_erreurs
async def modifier_reglages(conversation_id: str, corps: MajReglages) -> ReglagesConversation:
    """Fusionne un patch partiel avec les réglages existants. Fournir tous les champs équivaut à un remplacement."""
    actuels = depot.lire_reglages(conversation_id)
    return depot.ecrire_reglages(conversation_id, fusionner_reglages(actuels, corps))


@routeur.get("/outils", response_model=list[OutilDisponible])
async def catalogue_outils() -> list[OutilDisponible]:
    """Outils du registre, avec leur groupe et ce que leur déclaration coûte en tokens.

    Le coût est MESURÉ avec le tokenizer du modèle chargé, jamais estimé sur un ratio
    caractères/tokens : sur un vocabulaire de 248 320 entrées, l'estimation se trompe assez pour
    faire croire qu'un outil est gratuit. Sans modèle chargé, le champ vaut `null` — une absence
    nommée plutôt qu'un zéro qui se lirait comme « ne coûte rien ».
    """
    from backend.outils import descriptions, groupes

    familles = groupes()
    couts = await _couts_declarations([d.vers_format_moteur() for d in descriptions()])
    return [
        OutilDisponible(
            nom=description.nom,
            description=description.description,
            groupe=familles.get(description.nom, "autre"),
            tokens_definition=cout,
        )
        for description, cout in zip(descriptions(), couts, strict=True)
    ]


async def _couts_declarations(declarations: list[dict[str, object]]) -> list[int | None]:
    """Coût en tokens de chaque déclaration, ou `None` partout si rien n'est mesurable."""
    from backend.inference import superviseur

    textes = [json.dumps(declaration, ensure_ascii=False) for declaration in declarations]
    try:
        comptage = await superviseur.compter_tokens(textes)
    except Exception as exc:  # noqa: BLE001 — un coût est un confort, jamais une condition
        logger.debug("Coût des déclarations d'outils non mesurable ({}) : champ laissé vide.", exc)
        return [None] * len(textes)
    if not comptage.possible or len(comptage.tokens) != len(textes):
        return [None] * len(textes)
    return list(comptage.tokens)


@routeur.get("/conversations/{conversation_id}/outils", response_model=SelectionOutils)
@_traduire_erreurs
async def lire_outils(conversation_id: str) -> SelectionOutils:
    """Outils actifs de la conversation. `null` = tous, `[]` = aucun."""
    depot.exiger_conversation(conversation_id)
    return SelectionOutils(outils_actifs=depot.lire_reglages(conversation_id).outils_actifs)


@routeur.patch("/conversations/{conversation_id}/outils", response_model=SelectionOutils)
@_traduire_erreurs
async def modifier_outils(conversation_id: str, corps: SelectionOutils) -> SelectionOutils:
    """Remplace la sélection. Un nom inconnu du registre est accepté puis ignoré à l'usage.

    Refuser à l'enregistrement rendrait invalide un réglage écrit hier dès qu'un outil est renommé,
    et l'utilisateur perdrait toute sa sélection pour un seul nom devenu obsolète.
    """
    actuels = depot.lire_reglages(conversation_id)
    ecrits = depot.ecrire_reglages(
        conversation_id, actuels.model_copy(update={"outils_actifs": corps.outils_actifs}))
    return SelectionOutils(outils_actifs=ecrits.outils_actifs)


@routeur.post("/conversations/{conversation_id}/compacter", response_model=InfoCompaction)
@_traduire_erreurs
async def compacter(conversation_id: str, corps: DemandeCompaction) -> InfoCompaction:
    """Compaction manuelle (`/compact [instructions]`) de la branche affichée, tout de suite."""
    depot.exiger_conversation(conversation_id)
    return await compacter_maintenant(conversation_id, corps.instructions)


@routeur.get("/conversations/{conversation_id}/projet")
@_traduire_erreurs
async def lire_projet(conversation_id: str) -> LiaisonProjet:
    """Projet confié à la conversation, `null` si aucun."""
    depot.exiger_conversation(conversation_id)
    return LiaisonProjet(projet=depot.lire_reglages(conversation_id).projet)


@routeur.patch("/conversations/{conversation_id}/projet")
@_traduire_erreurs
async def modifier_projet(conversation_id: str, corps: LiaisonProjet) -> LiaisonProjet:
    """Confie un projet existant à la conversation (`null` le lui retire). Un nom inconnu est refusé."""
    projet = corps.projet
    if projet is not None:
        chemin_projet(projet)
    actuels = depot.lire_reglages(conversation_id)
    ecrits = depot.ecrire_reglages(conversation_id, actuels.model_copy(update={"projet": projet}))
    logger.info("Conversation {} : projet {}", conversation_id, ecrits.projet or "retiré")
    return LiaisonProjet(projet=ecrits.projet)


@routeur.get("/conversations/{conversation_id}/messages", response_model=list[MessageChat])
@_traduire_erreurs
async def lister_messages(conversation_id: str) -> list[MessageChat]:
    """Chemin actif, de la racine à la feuille affichée, dans l'ordre d'écriture."""
    depot.exiger_conversation(conversation_id)
    return depot.lister_messages(conversation_id)


@routeur.get("/conversations/{conversation_id}/branche", response_model=EtatBranche)
@_traduire_erreurs
async def lire_branche(conversation_id: str) -> EtatBranche:
    """Vue courante : chemin actif, feuille, et variantes de chaque message du chemin."""
    depot.exiger_conversation(conversation_id)
    return depot.lire_branche(conversation_id)


@routeur.post("/conversations/{conversation_id}/branche", response_model=EtatBranche)
@_traduire_erreurs
async def activer_branche(conversation_id: str, corps: ActivationBranche) -> EtatBranche:
    """Bascule la vue vers la branche contenant ce message, et rend la vue obtenue.

    Sert les flèches « ‹ 2 / 3 › » du frontend : on lui envoie l'identifiant de la variante
    choisie, il reçoit le chemin complet à afficher — il n'a aucun arbre à reconstruire.
    """
    depot.exiger_conversation(conversation_id)
    return depot.activer_branche(conversation_id, corps.message_id)


@routeur.get("/conversations/{conversation_id}/arbre", response_model=ArbreConversation)
@_traduire_erreurs
async def lire_arbre(conversation_id: str) -> ArbreConversation:
    """Tous les messages, branches abandonnées comprises : rien n'est perdu, et ça se vérifie."""
    return depot.lire_arbre(conversation_id)


@routeur.delete("/conversations/{conversation_id}/messages")
@_traduire_erreurs
async def vider_messages(conversation_id: str) -> dict[str, int]:
    """Vide l'historique en conservant la conversation et ses réglages."""
    return {"supprimes": depot.supprimer_messages(conversation_id)}


@routeur.post("/conversations/{conversation_id}/generer", response_class=StreamingResponse)
@_traduire_erreurs
async def generer(conversation_id: str, corps: DemandeGeneration) -> StreamingResponse:
    """Ouvre un flux SSE de génération.

    La préparation est faite avant de rendre la réponse : une conversation inconnue ou une
    génération déjà en cours restent de vrais statuts HTTP (404, 409). Passé ce point, les en-têtes
    sont partis et tout échec devient un événement `erreur` dans le flux.
    """
    return _flux(generation.preparer(conversation_id, corps))


@routeur.post("/conversations/{conversation_id}/messages/{message_id}/rejouer", response_class=StreamingResponse)
@_traduire_erreurs
async def rejouer_message(conversation_id: str, message_id: str, corps: DemandeRejeu) -> StreamingResponse:
    """Rejoue un message dans une sous-branche, et streame la réponse obtenue.

    Sur une réponse du modèle : une nouvelle réponse naît sous le même parent, l'ancienne reste
    accessible en variante. Sur un message utilisateur : son texte est renvoyé tel quel dans une
    branche sœur. Dans les deux cas, l'existant est conservé.
    """
    return _flux(generation.preparer_rejeu(conversation_id, message_id, corps))


@routeur.post("/conversations/{conversation_id}/messages/{message_id}/editer", response_class=StreamingResponse)
@_traduire_erreurs
async def editer_message(conversation_id: str, message_id: str, corps: DemandeEdition) -> StreamingResponse:
    """Édite un message utilisateur : nouvelle branche depuis son parent, puis génération.

    L'historique n'est jamais réécrit — le message d'origine et la réponse qu'il avait obtenue
    restent lisibles dans l'arbre. Éditer une réponse du modèle est refusé (422).
    """
    return _flux(generation.preparer_edition(conversation_id, message_id, corps))


def _flux(preparation: generation.PreparationGeneration) -> StreamingResponse:
    """Enveloppe SSE commune : un seul endroit décide des en-têtes et du type de média."""
    return StreamingResponse(
        _encoder_flux(preparation),
        media_type=flux_sse.TYPE_MEDIA_SSE,
        headers=flux_sse.ENTETES_SSE,
    )


async def _encoder_flux(preparation: generation.PreparationGeneration) -> AsyncIterator[str]:
    async for evenement in generation.diffuser(preparation):
        yield flux_sse.encoder(evenement)


@routeur.post("/conversations/{conversation_id}/annuler")
@_traduire_erreurs
async def annuler_generation(conversation_id: str) -> dict[str, bool]:
    """Demande l'arrêt de la génération en cours. `annulee` vaut `false` s'il n'y en avait aucune."""
    depot.exiger_conversation(conversation_id)
    return {"annulee": await annulation.annuler_et_attendre(conversation_id)}
