"""Routes HTTP du domaine `projets` : catalogue, création, instantanés, aperçu, contenu et modifications."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from backend.projets import apercu, contenu, instantanes, racine
from backend.projets.modeles import (
    ArbreProjet,
    CatalogueProjets,
    ContenuFichier,
    DemandeApercu,
    DemandeCreation,
    DiffFichier,
    EtatApercu,
    Instantane,
    ModificationsProjet,
    Projet,
)

routeur = APIRouter(prefix="/projets", tags=["projets"])


@routeur.get("", response_model=CatalogueProjets)
async def lister_projets() -> CatalogueProjets:
    return await asyncio.to_thread(racine.catalogue)


@routeur.post("", response_model=Projet)
async def creer_projet(corps: DemandeCreation) -> Projet:
    return await asyncio.to_thread(racine.creer, corps.nom)


@routeur.get("/{nom}/instantanes", response_model=list[Instantane])
async def lister_instantanes(nom: str) -> list[Instantane]:
    return await asyncio.to_thread(instantanes.lister, nom)


@routeur.post("/{nom}/instantanes/{sha}/restaurer")
async def restaurer_instantane(nom: str, sha: str) -> dict[str, str | None]:
    filet = await asyncio.to_thread(instantanes.restaurer, nom, sha)
    return {"restaure": sha, "filet": filet}


@routeur.get("/{nom}/apercu", response_model=EtatApercu)
async def lire_apercu(nom: str) -> EtatApercu:
    return await asyncio.to_thread(apercu.lire, nom)


@routeur.post("/{nom}/apercu", response_model=EtatApercu)
async def pointer_apercu(nom: str, corps: DemandeApercu) -> EtatApercu:
    return await asyncio.to_thread(apercu.pointer, nom, corps.port)


@routeur.get("/{nom}/arbre", response_model=ArbreProjet)
async def lire_arbre(nom: str) -> ArbreProjet:
    return await asyncio.to_thread(contenu.arbre, nom)


@routeur.get("/{nom}/fichier", response_model=ContenuFichier)
async def lire_fichier(nom: str, chemin: str) -> ContenuFichier:
    return await asyncio.to_thread(contenu.lire, nom, chemin)


@routeur.get("/{nom}/modifications", response_model=ModificationsProjet)
async def lire_modifications(nom: str) -> ModificationsProjet:
    return await asyncio.to_thread(instantanes.modifications, nom)


@routeur.get("/{nom}/diff", response_model=DiffFichier)
async def lire_diff(nom: str, chemin: str) -> DiffFichier:
    return await asyncio.to_thread(instantanes.diff, nom, chemin)
