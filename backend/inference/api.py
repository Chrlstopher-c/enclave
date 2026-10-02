"""Routes HTTP du domaine inference : planifier, dégrader, charger, observer, générer, décharger.

Cette couche ne contient aucune logique métier. Elle assemble deux sous-modules — le planificateur,
qui décide, et les adaptateurs, qui appliquent — et traduit les erreurs métier en réponses HTTP à
partir du statut que chaque erreur porte déjà, sans table de correspondance dupliquée ici.

Le plan reste seule source de vérité : `/planifier` le rend avec ses justifications, `/charger`
l'applique tel quel. Le frontend l'affiche, il ne le recalcule jamais. Après un échec, `/degrader`
rend un plan strictement plus conservateur — jamais plus ambitieux, c'était l'escalade de la v1.

Montage attendu dans l'application : `app.include_router(routeur_inference)` — le préfixe
`/api/inference` est porté par le routeur lui-même.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field, model_validator

from backend.core import EchoHubError, MoteurIndisponible
from backend.engines import service as engines_service
from backend.inference.engines_adapters import (
    CauseEchec,
    EtatChargement,
    MessageChat,
    MoteurSupporte,
    OptionsGeneration,
    PlanChargement,
    Sante,
    SessionChargement,
    StatutInference,
    superviseur,
    texte_de,
)
from backend.inference.hygiene_historique import pour_le_modele
from backend.inference.engines_adapters.contrat import OccupationContexte
from backend.inference.engines_adapters.traduction_plan import vers_cause_planificateur, vers_plan_moteur
from backend.inference.planner import DemandeDeChargement, PlanDeChargement, degrader, planifier

# Préfixe SANS `/api` : nginx réécrit `/api/(.*)` en `/$1` avant de proxifier vers ce backend
# (docker/nginx.conf). Le conserver ici exposerait la route sous `/api/api/inference` côté
# navigateur, alors que les autres domaines montent bien `/system`, `/engines`, `/chat`.
router = APIRouter(prefix="/inference", tags=["inference"])
routeur_inference = router

# En-têtes indispensables au streaming derrière nginx : sans `X-Accel-Buffering`, le proxy tamponne
# la réponse et les tokens arrivent en bloc à la fin — le streaming devient invisible.
ENTETES_FLUX = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}

DELAI_ATTENTE_MAX_S = 600.0

# Bornes de la mesure d'occupation du contexte. Elles ne décrivent aucun matériel : elles bornent
# le travail d'une route appelée à chaque accalmie de la conversation. Au-delà, on refuse
# explicitement plutôt que de tokeniser un volume arbitraire dans le fil du moteur.
MAX_MESSAGES_COMPTAGE = 4_000
MAX_CARACTERES_COMPTAGE = 4_000_000


class ReponsePlan(BaseModel):
    """Plan et ses justifications, prêts à l'affichage : l'interface ne recalcule rien."""

    plan: PlanDeChargement
    justifications: list[str]
    avertissements: list[str]


class RequetePlanification(BaseModel):
    """Entrées mesurées du planificateur : métadonnées du modèle, profil machine, préférences."""

    demande: DemandeDeChargement


class RequeteDegradation(BaseModel):
    """Replanification après échec. La cause vient de l'échec observé, pas d'une supposition."""

    demande: DemandeDeChargement
    plan_echoue: PlanDeChargement
    cause: CauseEchec | None = None


class RequeteChargement(BaseModel):
    """Chargement : soit on applique un plan déjà affiché, soit on en fait calculer un.

    Appliquer le plan déjà montré à l'utilisateur garantit que ce qui est chargé est exactement ce
    qu'il a validé — replanifier ici produirait un autre plan, la VRAM libre ayant pu changer.

    `chemin_modele` est fourni par l'appelant : le planificateur raisonne sur un identifiant, la
    résolution vers un fichier appartient au domaine `models`.
    """

    chemin_modele: str = Field(min_length=1)
    plan: PlanDeChargement | None = None
    demande: DemandeDeChargement | None = None

    @model_validator(mode="after")
    def _exiger_une_source(self) -> RequeteChargement:
        if (self.plan is None) == (self.demande is None):
            raise ValueError("Fournir soit `plan`, soit `demande` — jamais les deux, jamais aucun.")
        return self


class RequeteGeneration(BaseModel):
    """Conversation à poursuivre et réglages d'échantillonnage."""

    messages: list[MessageChat] = Field(min_length=1)
    options: OptionsGeneration = Field(default_factory=OptionsGeneration)


class RequeteOccupationContexte(BaseModel):
    """Textes dont on veut le coût réel en tokens : prompt système et messages de la conversation.

    L'appelant envoie ce qu'il affiche, le backend mesure. Il ne relit pas la conversation en base :
    le domaine `inference` ne connaît pas la persistance de `chat`, et l'utilisateur doit voir le
    coût de ce qu'il a sous les yeux, brouillon de saisie compris.
    """

    prompt_systeme: str = ""
    messages: list[MessageChat] = Field(default_factory=list, max_length=MAX_MESSAGES_COMPTAGE)

    @model_validator(mode="after")
    def _borner_volume(self) -> RequeteOccupationContexte:
        total = len(self.prompt_systeme) + sum(len(texte_de(message)) for message in self.messages)
        if total > MAX_CARACTERES_COMPTAGE:
            raise ValueError(
                f"Volume à mesurer trop grand : {total} caractères pour un plafond de "
                f"{MAX_CARACTERES_COMPTAGE}."
            )
        return self


def _en_http(exc: EchoHubError) -> HTTPException:
    """Traduit une erreur métier en réponse HTTP, en gardant code, message et remédiation."""
    return HTTPException(status_code=exc.statut_http, detail=exc.to_dict())


def _reponse_plan(plan: PlanDeChargement) -> ReponsePlan:
    return ReponsePlan(
        plan=plan,
        justifications=list(plan.justifications()),
        avertissements=list(plan.avertissements),
    )


@router.post("/planifier", response_model=ReponsePlan)
def planifier_chargement(requete: RequetePlanification) -> ReponsePlan:
    """Calcule un plan sans rien charger : c'est ce que l'interface affiche avant de décider."""
    try:
        return _reponse_plan(planifier(requete.demande))
    except EchoHubError as exc:
        raise _en_http(exc) from exc


@router.post("/degrader", response_model=ReponsePlan)
def degrader_plan(requete: RequeteDegradation) -> ReponsePlan:
    """Rend un plan strictement plus conservateur après un échec de chargement."""
    cause = requete.cause if requete.cause is not None else superviseur.statut().cause
    try:
        return _reponse_plan(degrader(requete.demande, requete.plan_echoue, vers_cause_planificateur(cause)))
    except EchoHubError as exc:
        raise _en_http(exc) from exc


def _plan_moteur(requete: RequeteChargement) -> PlanChargement:
    """Résout le plan à appliquer, en planifiant seulement si l'appelant n'en fournit pas."""
    if requete.plan is not None:
        return vers_plan_moteur(requete.plan, requete.chemin_modele)
    try:
        plan = planifier(requete.demande)  # type: ignore[arg-type] - garanti non nul par le validateur
    except EchoHubError as exc:
        raise _en_http(exc) from exc
    return vers_plan_moteur(plan, requete.chemin_modele)


async def _verifier_moteur_disponible(moteur: MoteurSupporte) -> None:
    """Refuse un chargement dont le moteur ciblé n'est plus fonctionnel, plan déjà construit ou non.

    `/planifier` filtre déjà les moteurs cassés (`choisir_moteur`, sur `moteurs_disponibles`), mais
    un plan appliqué tel quel (`RequeteChargement.plan`, cf. `_plan_moteur`) ne repasse jamais par ce
    filtre — voulu pour ne pas replanifier sur une VRAM qui a bougé entre l'affichage et la
    confirmation. Cela laisse passer un plan devenu caduc si le moteur est tombé ENTRE les deux
    appels. Mesuré le 2026-08-28 : `ggml_cuda_init: failed to initialize CUDA: unknown error` rend
    llama.cpp défaillant en cours de session, sans qu'aucun code ne le revérifie avant de lancer le
    sous-processus — un chargement pouvait alors être accepté puis rester bloqué sans jamais servir.
    """
    sonde = engines_service.sante_llamacpp if moteur is MoteurSupporte.LLAMA_CPP else engines_service.sante_vllm
    sante = await sonde()
    if not sante.fonctionnel:
        raise MoteurIndisponible(
            f"Le moteur {moteur.value} n'est plus fonctionnel : {sante.diagnostic}",
            remediation=sante.remediation,
            details={"moteur": moteur.value, "statut": sante.statut.value},
        )


@router.post("/charger", response_model=StatutInference, status_code=202)
async def charger_modele(requete: RequeteChargement) -> StatutInference:
    """Démarre le chargement et rend la main aussitôt — l'avancement se lit sur `/etat`."""
    plan = _plan_moteur(requete)
    try:
        await _verifier_moteur_disponible(plan.moteur)
        return await superviseur.demarrer_chargement(plan)
    except EchoHubError as exc:
        raise _en_http(exc) from exc


@router.get("/etat", response_model=StatutInference)
def lire_etat() -> StatutInference:
    """État courant : inactif, en cours, prêt, ou échoué avec sa cause qualifiée."""
    return superviseur.statut()


@router.get("/etat/attendre", response_model=StatutInference)
async def attendre_etat(delai_s: float = Query(default=60.0, gt=0, le=DELAI_ATTENTE_MAX_S)) -> StatutInference:
    """Attend la fin du chargement dans une fenêtre bornée, pour les clients qui ne sondent pas."""
    return await superviseur.attendre(delai_s)


@router.get("/journal", response_model=list[SessionChargement])
def lire_journal(limite: int = Query(default=10, ge=1, le=50)) -> list[SessionChargement]:
    """Journal des derniers chargements : plan appliqué, déroulé, issue."""
    return superviseur.journal(limite)


@router.get("/sante", response_model=Sante)
async def sonder_sante() -> Sante:
    """Sonde le moteur maintenant — un moteur mort n'apparaît pas dans l'état mémorisé."""
    return await superviseur.sante()


@router.post("/contexte", response_model=OccupationContexte)
async def mesurer_occupation_contexte(requete: RequeteOccupationContexte) -> OccupationContexte:
    """Décompose l'occupation de la fenêtre de contexte du modèle chargé, poste par poste.

    Répond 200 même quand rien n'est mesurable : « aucun modèle chargé » n'est pas une erreur mais
    une absence de tokenizer, et la réponse la nomme (`mesurable: false` + `raison`) — exactement ce
    que fait `/sante` avec `disponible: false`. Un 4xx obligerait l'interface à traduire un état
    normal en échec.

    Le comptage passe par le tokenizer du modèle réellement chargé. Ce qu'il ne couvre pas est listé
    dans `avertissements` plutôt que comblé par une estimation.

    Les blocs d'outils sont réduits AVANT d'être comptés, exactement comme la génération les réduit
    avant de les envoyer (`hygiene_historique.pour_le_modele`). L'interface envoie ce qu'elle
    AFFICHE, qui reste entier ; sans ce passage, le panneau annoncerait une occupation que le
    modèle ne subit pas — et un panneau de contexte qui se trompe sur le contexte ne sert à rien.
    """
    mesures = [
        message.model_copy(update={"content": pour_le_modele(message.content)})
        if isinstance(message.content, str)
        else message
        for message in requete.messages
    ]
    try:
        return await superviseur.compter_contexte(requete.prompt_systeme, mesures)
    except EchoHubError as exc:
        raise _en_http(exc) from exc


@router.post("/decharger", response_model=StatutInference)
async def decharger_modele() -> StatutInference:
    """Éjecte le modèle courant et vérifie que la VRAM est réellement rendue."""
    try:
        return await superviseur.decharger()
    except EchoHubError as exc:
        raise _en_http(exc) from exc


def _evenement(charge: dict[str, Any]) -> str:
    return f"data: {json.dumps(charge, ensure_ascii=False)}\n\n"


async def _flux_sse(requete: RequeteGeneration) -> AsyncIterator[str]:
    """Sérialise le flux de morceaux en SSE. Une erreur en cours de flux devient un événement.

    Le statut HTTP est déjà parti quand la génération commence : signaler l'échec dans le flux est
    la seule façon d'en informer le client sans le laisser attendre une fin qui ne viendra pas.
    """
    try:
        async for morceau in superviseur.generer(requete.messages, requete.options):
            yield _evenement(morceau.model_dump())
    except EchoHubError as exc:
        logger.error("Génération interrompue : {}", exc)
        yield _evenement({"type": "erreur", **exc.to_dict()})
    except Exception as exc:  # le flux doit se fermer proprement même sur une erreur non métier
        logger.exception("Génération interrompue par une erreur non qualifiée")
        yield _evenement({"type": "erreur", "message": str(exc)})
    yield "data: [DONE]\n\n"


@router.post("/generer")
async def generer(requete: RequeteGeneration) -> StreamingResponse:
    """Flux de tokens en SSE. Refuse d'emblée si aucun modèle n'est prêt."""
    statut = superviseur.statut()
    if statut.etat is not EtatChargement.PRET:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "aucun_modele_pret",
                "message": f"Aucun modèle prêt (état : {statut.etat.value}).",
                "remediation": "Charger un modèle avant de générer.",
            },
        )
    return StreamingResponse(_flux_sse(requete), media_type="text/event-stream", headers=ENTETES_FLUX)
