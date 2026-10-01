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


class EntreeArbre(BaseModel):
    """Un fichier du projet, chemin relatif en `/`. Les dossiers se déduisent des chemins."""

    chemin: str
    taille: int


class ArbreProjet(BaseModel):
    """`tronque` vrai = plus de fichiers que la borne : la liste est partielle, et le dit."""

    fichiers: list[EntreeArbre]
    tronque: bool = False


class ContenuFichier(BaseModel):
    chemin: str
    taille: int
    contenu: str | None
    binaire: bool = False
    tronque: bool = False


class Modification(BaseModel):
    """Changement d'un fichier depuis l'instantané de référence. `etat` : A (ajouté), M, D (supprimé)."""

    chemin: str
    etat: str
    ajouts: int | None = None
    suppressions: int | None = None


class ModificationsProjet(BaseModel):
    """Changements depuis le DERNIER instantané, pris avant le tour en cours ou le dernier tour."""

    reference: Instantane | None
    fichiers: list[Modification] = Field(default_factory=list)


class DiffFichier(BaseModel):
    chemin: str
    diff: str
    tronque: bool = False
