"""Routes HTTP du domaine `projets` : catalogue, création, instantanés et restauration."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from backend.projets import instantanes, racine
from backend.projets.modeles import CatalogueProjets, DemandeCreation, Instantane, Projet

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
