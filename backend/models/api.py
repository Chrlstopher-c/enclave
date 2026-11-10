"""Routes HTTP du domaine `models` — recherche Hub, registre local, transferts.

Le routeur appartient à la tranche verticale du domaine : il vit à côté du métier qu'il expose et
n'ajoute aucune règle. Toute décision — quoi télécharger, quelles métadonnées sont lisibles, ce
qu'un écart de cohérence signifie — appartient aux modules du domaine ; ici on traduit, on ne
décide pas.

Deux distinctions du domaine sont préservées telles quelles dans les réponses, parce que les
confondre est précisément l'erreur que la v1 commettait :

- ce que le Hub **annonce** (`/recherche`, `/depots/{depot}`) n'est jamais présenté comme mesuré ;
- ce que le fichier **contient** (`/registre/{id}/metadonnees`) est lu dans l'en-tête, et vaut
  `null` quand il n'est pas lisible — jamais une estimation déguisée en mesure.

Ordre de déclaration : les chemins littéraux (`/registre/synchronisation`, `/telechargements/flux`)
précèdent les chemins paramétrés qui les engloberaient. FastAPI retient la première route qui
correspond ; inverser l'ordre ferait passer « synchronisation » pour un identifiant de modèle.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from backend.core import EchoHubError
from backend.models import (
    FormatRecherche,
    MetadonneesGGUF,
    MetadonneesSafetensors,
    ModeleEnregistre,
    Ordre,
    PageRecherche,
    RapportCoherence,
    ResultatRecherche,
    ResumeSynchronisation,
    Telechargement,
    TriRecherche,
    details,
    gestionnaire,
    lister_modeles,
    marquer_favori,
    metadonnees_modele,
    metadonnees_safetensors_modele,
    obtenir_modele,
    oublier_modele,
    rechercher,
    synchroniser_registre,
    verifier_modele_enregistre,
)

# Import direct du sous-module, comme pour `download` ci-dessous : `capacites` appartient au même
# domaine que ce routeur, la frontière publique de `models` ne concerne que les autres domaines.
from backend.models.capacites import Capacite, CapaciteDeduite, DefinitionCapacite, definitions
from backend.models.disque import DossierDisque
from backend.models.disque import inventaire as inventaire_disque
from backend.models.disque import supprimer_dossier
from backend.models.download import ETATS_TERMINAUX, INTERVALLE_DIFFUSION_S, MAX_ITERATIONS_DIFFUSION
from backend.models.registry import capacites as capacites_modele

# Préfixe SANS `/api` : nginx réécrit `/api/(.*)` en `/$1` avant de proxifier (docker/nginx.conf).
router = APIRouter(prefix="/models", tags=["models"])

# Sans `X-Accel-Buffering`, nginx tamponne la réponse et la progression d'un transfert de plusieurs
# gigaoctets n'arrive au navigateur qu'une fois le transfert fini — c'est-à-dire jamais à temps.
ENTETES_FLUX = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}


class DemandeTelechargement(BaseModel):
    """Un fichier précis du dépôt, ou le dépôt entier si `fichier` est omis."""

    depot: str = Field(min_length=1)
    fichier: str | None = None
    revision: str = "main"


class ResultatOubli(BaseModel):
    """Réponse explicite plutôt qu'un 204 muet : l'interface affiche ce qui a été fait."""

    oublie: bool


def _en_http(exc: EchoHubError) -> HTTPException:
    """Traduit une erreur métier en réponse HTTP à partir du statut qu'elle porte déjà."""
    return HTTPException(status_code=exc.statut_http, detail=exc.to_dict())


# ------------------------------------------------------------------ recherche sur le Hub


@router.get("/recherche", response_model=PageRecherche)
def rechercher_depots(
    requete: str = Query(default=""),
    formats: list[FormatRecherche] = Query(default_factory=list),
    capacites: list[Capacite] = Query(default_factory=list),
    tri: TriRecherche = Query(default=TriRecherche.TELECHARGEMENTS),
    ordre: Ordre = Query(default="desc"),
    page: int = Query(default=0, ge=0),
    taille_page: int = Query(default=20, ge=1, le=100),
) -> PageRecherche:
    """Page de dépôts du Hub. Tout ce qui revient ici est **annoncé**, rien n'est mesuré.

    `capacites` se répète pour se combiner et vaut ET : `?capacites=vision&capacites=appel_outils`
    ne garde que les dépôts qui laissent entendre les deux. Paramètre facultatif ajouté après coup —
    les appels existants (`requete`, `formats`, `tri`, `ordre`, `page`, `taille_page`) se comportent
    exactement comme avant lorsqu'il est absent.
    """
    try:
        return rechercher(
            requete,
            formats=formats,
            capacites=capacites,
            tri=tri,
            ordre=ordre,
            page=page,
            taille_page=taille_page,
        )
    except EchoHubError as exc:
        raise _en_http(exc) from exc


@router.get("/capacites", response_model=list[DefinitionCapacite])
def lister_capacites() -> list[DefinitionCapacite]:
    """Vocabulaire des capacités filtrables, définitions comprises.

    Publié pour que l'interface compose ses filtres à partir de la liste qui filtre réellement : une
    énumération recopiée côté frontend finirait par proposer un filtre que le backend ne connaît pas.
    """
    return definitions()


@router.get("/depots/{depot:path}", response_model=ResultatRecherche)
def fiche_depot(depot: str) -> ResultatRecherche:
    """Fiche complète d'un dépôt. `:path` parce qu'un identifiant Hub contient un `/`."""
    try:
        return details(depot)
    except EchoHubError as exc:
        raise _en_http(exc) from exc


# ------------------------------------------------------------------------- registre local


@router.get("/registre", response_model=list[ModeleEnregistre])
def lister_registre() -> list[ModeleEnregistre]:
    """Modèles présents sur le disque et connus du registre."""
    return lister_modeles()


@router.get("/disque", response_model=list[DossierDisque])
def lister_disque() -> list[DossierDisque]:
    """TOUT ce que la racine des modèles contient, inscrit au registre ou non.

    Le registre n'expose que le chargeable ; cette route expose l'occupé. Sans elle, un dossier
    refusé était invisible et sa place indestructible depuis l'interface.
    """
    return inventaire_disque()


@router.delete("/disque/{dossier:path}")
def supprimer_du_disque(dossier: str) -> dict[str, object]:
    """Efface un dossier de modèles. Irréversible : les octets partent réellement."""
    try:
        liberes = supprimer_dossier(dossier)
    except EchoHubError as exc:
        raise _en_http(exc) from exc
    return {"dossier": dossier, "octets_liberes": liberes}


@router.post("/registre/synchronisation", response_model=ResumeSynchronisation)
def synchroniser() -> ResumeSynchronisation:
    """Réaligne le registre sur le contenu réel du disque — le disque fait autorité."""
    try:
        return synchroniser_registre()
    except EchoHubError as exc:
        raise _en_http(exc) from exc


# `:path` sur l'identifiant, et les routes SUFFIXÉES déclarées avant la route nue.
#
# Un identifiant de registre vaut `<depot>::<fichier>` et le dépôt contient un `/`
# (`mradermacher/Qwen3.6-27B-…-GGUF::…gguf`). Le navigateur l'encode bien en `%2F`, mais le
# serveur le décode AVANT le routage : un paramètre à segment unique ne correspond alors plus, et
# toutes les routes du registre répondaient 404 sur les modèles issus du Hub — seuls les dossiers
# sans `/` fonctionnaient, ce qui donnait un défaut à moitié visible.
#
# `{identifiant:path}` est glouton : déclaré avant, il avalerait `/metadonnees` et `/coherence`
# dans l'identifiant lui-même. L'ordre ci-dessous n'est donc pas cosmétique.
class MajFavori(BaseModel):
    """Marque posée par l'utilisateur — jamais déduite d'un usage ni d'une fréquence."""

    favori: bool


@router.put("/registre/{identifiant:path}/favori", response_model=ModeleEnregistre)
def basculer_favori(identifiant: str, maj: MajFavori) -> ModeleEnregistre:
    """Range ou retire un modèle des favoris. L'entrée mise à jour est rendue telle quelle."""
    try:
        return marquer_favori(identifiant, maj.favori)
    except EchoHubError as exc:
        raise _en_http(exc) from exc


@router.get("/registre/{identifiant:path}/metadonnees", response_model=MetadonneesGGUF | None)
def lire_metadonnees(identifiant: str) -> MetadonneesGGUF | None:
    """Métadonnées LUES dans l'en-tête GGUF — seule entrée valable du planificateur.

    `null` quand le modèle n'est pas au format GGUF : l'appelant doit décider quoi en faire, il ne
    reçoit jamais une valeur inventée à la place.
    """
    try:
        return metadonnees_modele(identifiant)
    except EchoHubError as exc:
        raise _en_http(exc) from exc


@router.get("/registre/{identifiant:path}/metadonnees-safetensors", response_model=MetadonneesSafetensors | None)
def lire_metadonnees_safetensors(identifiant: str) -> MetadonneesSafetensors | None:
    """Métadonnées LUES dans le `config.json` safetensors — entrée du planificateur pour ce format.

    `null` quand le modèle n'est pas au format safetensors : symétrique de `/metadonnees` pour le
    GGUF. Poids par bloc mesuré sur l'index des tenseurs, jamais estimé.
    """
    try:
        return metadonnees_safetensors_modele(identifiant)
    except EchoHubError as exc:
        raise _en_http(exc) from exc


@router.get("/registre/{identifiant:path}/capacites", response_model=list[CapaciteDeduite])
def lire_capacites(identifiant: str) -> list[CapaciteDeduite]:
    """Capacités DÉDUITES d'un modèle local — des conclusions tracées, pas des mesures.

    Chaque entrée porte les indices qui l'ont produite ; une liste vide dit que rien n'est
    reconnaissable localement, pas que le modèle est dépourvu de ces capacités.
    """
    try:
        return capacites_modele(identifiant)
    except EchoHubError as exc:
        raise _en_http(exc) from exc


@router.get("/registre/{identifiant:path}/coherence", response_model=RapportCoherence)
def verifier(identifiant: str) -> RapportCoherence:
    """Confronte ce que le modèle déclare à ce qu'il contient réellement."""
    try:
        return verifier_modele_enregistre(identifiant)
    except EchoHubError as exc:
        raise _en_http(exc) from exc


@router.get("/registre/{identifiant:path}", response_model=ModeleEnregistre)
def lire_modele(identifiant: str) -> ModeleEnregistre:
    try:
        return obtenir_modele(identifiant)
    except EchoHubError as exc:
        raise _en_http(exc) from exc


@router.delete("/registre/{identifiant:path}", response_model=ResultatOubli)
def oublier(identifiant: str) -> ResultatOubli:
    """Retire l'entrée du registre. Les fichiers restent sur le disque, délibérément."""
    try:
        oublier_modele(identifiant)
    except EchoHubError as exc:
        raise _en_http(exc) from exc
    return ResultatOubli(oublie=True)


# ---------------------------------------------------------------------------- transferts


@router.get("/telechargements", response_model=list[Telechargement])
def lister_telechargements() -> list[Telechargement]:
    return gestionnaire().lister()


@router.post("/telechargements", response_model=Telechargement, status_code=202)
def demarrer_telechargement(demande: DemandeTelechargement) -> Telechargement:
    """Démarre le transfert et rend la main aussitôt — la suite se lit sur `/flux`."""
    try:
        return gestionnaire().demarrer(demande.depot, fichier=demande.fichier, revision=demande.revision)
    except EchoHubError as exc:
        raise _en_http(exc) from exc


def _evenement(etat: Telechargement) -> str:
    return f"data: {etat.model_dump_json()}\n\n"


async def _flux_global() -> AsyncIterator[str]:
    """Diffuse l'état de TOUS les transferts, chaque événement portant un état complet.

    État complet et non delta : un client qui se connecte en cours de route n'a rien à
    reconstituer. La boucle est bornée par `MAX_ITERATIONS_DIFFUSION`, exactement comme la
    diffusion par transfert du domaine — un navigateur fermé sans fermer proprement le flux ne doit
    pas laisser une tâche tourner sans fin.
    """
    gest = gestionnaire()
    dernier: str | None = None
    for _ in range(MAX_ITERATIONS_DIFFUSION):
        etats = gest.lister()
        empreinte = "|".join(etat.model_dump_json() for etat in etats)
        if empreinte != dernier:
            dernier = empreinte
            for etat in etats:
                yield _evenement(etat)
        if etats and all(etat.etat in ETATS_TERMINAUX for etat in etats):
            break
        await asyncio.sleep(INTERVALLE_DIFFUSION_S)
    else:
        logger.warning("Diffusion globale des transferts arrêtée sur sa borne d'itérations")
    yield "data: [DONE]\n\n"


@router.get("/telechargements/flux")
async def flux_telechargements() -> StreamingResponse:
    """Progression de tous les transferts en SSE. GET : `EventSource` ne sait pas faire autrement."""
    return StreamingResponse(_flux_global(), media_type="text/event-stream", headers=ENTETES_FLUX)


# `:path`, pour la même raison qu'au registre : un identifiant de transfert vaut
# `<depot>::<fichier>` et le dépôt contient un `/`. Le navigateur l'encode en %2F, le serveur le
# décode AVANT le routage, et un paramètre à segment unique ne correspond plus — annulation et
# relance répondaient 404 sur tout modèle venu du Hub.
#
# Les routes SUFFIXÉES viennent avant la route nue : `:path` est glouton et avalerait `/relance`
# et `/flux` dans l'identifiant.
@router.post("/telechargements/{identifiant:path}/relance", response_model=Telechargement)
def relancer_telechargement(identifiant: str) -> Telechargement:
    """Reprend un transfert interrompu là où il s'était arrêté."""
    try:
        return gestionnaire().relancer(identifiant)
    except EchoHubError as exc:
        raise _en_http(exc) from exc


@router.get("/telechargements/{identifiant:path}/flux")
async def flux_telechargement(identifiant: str) -> StreamingResponse:
    """Progression d'un transfert précis — la diffusion native du domaine."""

    async def flux() -> AsyncIterator[str]:
        try:
            async for etat in gestionnaire().suivre(identifiant):
                yield _evenement(etat)
        except EchoHubError as exc:
            logger.error("Diffusion de {} interrompue : {}", identifiant, exc)
            yield f"data: {exc.to_dict()}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(flux(), media_type="text/event-stream", headers=ENTETES_FLUX)


@router.get("/telechargements/{identifiant:path}", response_model=Telechargement)
def etat_telechargement(identifiant: str) -> Telechargement:
    try:
        return gestionnaire().etat(identifiant)
    except EchoHubError as exc:
        raise _en_http(exc) from exc


@router.delete("/telechargements/{identifiant:path}", response_model=Telechargement)
def annuler_telechargement(
    identifiant: str,
    supprimer_fichiers: bool = Query(default=False),
) -> Telechargement:
    """Le défaut CONSERVE les octets déjà écrits : un transfert de plusieurs Go doit pouvoir
    reprendre plutôt que repartir de zéro."""
    try:
        return gestionnaire().annuler(identifiant, supprimer_fichiers=supprimer_fichiers)
    except EchoHubError as exc:
        raise _en_http(exc) from exc
