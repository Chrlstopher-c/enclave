"""Formes publiques du domaine `projets` — ce que l'API et le chat échangent."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

MOTIF_NOM = r"^[a-z0-9][a-z0-9._-]{0,62}$"


class Projet(BaseModel):
    nom: str
    modifie_le: float
    instantanes: bool


class CatalogueProjets(BaseModel):
    """`actif` faux = aucune racine configurée : le mode projet n'existe pas sur cette installation."""

    actif: bool
    racine: str | None = None
    projets: list[Projet] = Field(default_factory=list)


class DemandeCreation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nom: str = Field(pattern=MOTIF_NOM)


class Instantane(BaseModel):
    sha: str
    date: float
    message: str


class LiaisonProjet(BaseModel):
    """Projet confié à une conversation. `None` = conversation ordinaire, sans dossier de projet."""

    model_config = ConfigDict(extra="forbid")

    projet: str | None = None


class EtatApercu(BaseModel):
    """Port servi par le relais d'aperçu, ports en écoute dans l'atelier, URL à ouvrir."""

    port: int | None
    ports: list[int]
    url: str


class DemandeApercu(BaseModel):
    port: int = Field(gt=1023, lt=65536)
