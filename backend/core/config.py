"""Configuration typée d'EchoHub v2 — source unique des chemins et des réglages runtime.

Règle héritée d'un défaut mesuré sur la v1 : aucun chemin absolu n'est codé en dur. La v1 portait
`/mnt/models/echohub` comme défaut dans cinq modules ; ce chemin tombait hors du volume Docker, et
chaque recréation du conteneur perdait les modèles téléchargés.

Deux invariants en découlent :
1. l'environnement prime sur tout défaut, sans exception ;
2. à défaut d'environnement, tout se range SOUS le répertoire de données de l'application — qui est
   précisément ce que l'infrastructure monte en volume persistant.
"""

from __future__ import annotations

import os
import platform
from functools import lru_cache
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.core.errors import ConfigurationInvalide

# Distinct de la v1 ("echohub") : les deux versions peuvent tourner sur la même machine sans
# partager XDG_DATA_HOME/echohub — la v1 y écrit un schéma anglais (`created_at`), incompatible
# avec le schéma v2 (`cree_le`). Mesuré : un backend v2 lisant ce répertoire plante ou corrompt.
NOM_APPLICATION = "echohub-v2"

# Sous-dossier attribué à chaque chemin dérivé quand la variable d'environnement est absente.
_SOUS_DOSSIERS: dict[str, str] = {
    "models_dir": "models",
    "engines_dir": "engines",
    "atelier_workspace": "ateliers",
    "agent_dir": "agent",
}

# Atelier d'exécution : conteneur de dev persistant, atteint par son nom sur le réseau interne de
# la pile (aucun port publié sur l'hôte). Le défaut vaut en conteneur ; hors Docker, l'atelier
# n'existe pas et les outils d'exécution rendent un repli explicite plutôt qu'un plantage.
_URL_ATELIER_DEFAUT = "http://echohub-atelier:8080"

_NIVEAUX_VALIDES = frozenset({"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"})

# Service SearXNG de la pile Docker, atteint par son nom sur le réseau interne (aucun port publié).
_URL_SEARXNG_DEFAUT = "http://searxng:8080"


def _racine_donnees_par_defaut() -> Path:
    """Racine de données propre à la plateforme, utilisée UNIQUEMENT si XDG_DATA_HOME est absent."""
    systeme = platform.system()
    if systeme == "Windows":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    if systeme == "Darwin":
        return Path.home() / "Library" / "Application Support"
    return Path.home() / ".local" / "share"


class Settings(BaseSettings):
    """Réglages du backend, lus dans l'environnement (le `.env` ne sert qu'au poste de dev)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        # Les défauts passent par les validateurs : c'est ce qui rend les chemins dérivés effectifs.
        validate_default=True,
    )

    # Déclaré en premier : les chemins dérivés ci-dessous s'appuient sur sa valeur déjà validée.
    data_home: Path = Field(default_factory=_racine_donnees_par_defaut, validation_alias="XDG_DATA_HOME")
    models_dir: Path = Field(default=None, validation_alias="MODELS_DIR")
    engines_dir: Path = Field(default=None, validation_alias="ENGINES_DIR")
    # Racine des espaces de travail par conversation, PARTAGÉE avec le conteneur atelier via un
    # volume commun : un fichier écrit ici par `ecrire_fichier` est vu par le shell de l'atelier,
    # et un fichier produit par une commande de l'atelier est balayé et rattaché à la conversation.
    atelier_workspace: Path = Field(default=None, validation_alias="ATELIER_WORKSPACE")
    # Maison de l'agent, PARTAGÉE entre toutes les conversations : SYSTEM.md, AWARENESS.md, mémoire,
    # skills, mcp.json. Le modèle y accède par le préfixe `~agent/` de ses outils de fichiers.
    agent_dir: Path = Field(default=None, validation_alias="ECHOHUB_AGENT_DIR")
    # `uid:gid` à qui rendre les fichiers écrits dans la maison (le backend Docker est root) ; vide = rien.
    agent_proprietaire: str = Field(default="", validation_alias="ECHOHUB_AGENT_PROPRIETAIRE")

    host: str = Field(default="127.0.0.1", validation_alias="ECHOHUB_HOST")
    # Distinct du port par défaut de la v1 (37821), qui peut tourner simultanément sur la même
    # machine. Mesuré : sur ce port-là, le bind de la v2 échouait avec "Address already in use"
    # pendant qu'un curl répondait 200 — servi par la v1, pas par elle.
    port: int = Field(default=37921, ge=1, le=65535, validation_alias="ECHOHUB_PORT")

    log_level: str = Field(default="INFO", validation_alias="ECHOHUB_LOG_LEVEL")
    log_to_file: bool = Field(default=True, validation_alias="ECHOHUB_LOG_TO_FILE")

    hf_token: SecretStr | None = Field(default=None, validation_alias="HF_TOKEN")
    db_timeout_s: float = Field(default=30.0, gt=0, validation_alias="ECHOHUB_DB_TIMEOUT_S")

    # Watchdog d'inactivité de génération : un moteur qui n'émet plus rien pendant ce délai est tenu
    # pour mort. Ce n'est PAS un budget de performance — c'est le temps qu'on laisse au préremplissage
    # d'un long prompt (35B, experts déportés en RAM) qui, sur un gros contexte, peut dépasser
    # plusieurs minutes AVANT le premier token, sans qu'aucun battement ne réarme le compteur. 180 s
    # coupait des générations vivantes ; 900 s laisse le travail lourd aboutir tout en finissant par
    # voir un vrai blocage. Les deux watchdogs (chat et flux moteur) lisent CE délai : le flux ne doit
    # jamais couper avant le chat, sans quoi il coupe le premier.
    delai_inactivite_generation_s: float = Field(
        default=900.0, gt=0, validation_alias="ECHOHUB_DELAI_INACTIVITE_S"
    )

    # Recherche web : nom de service Docker résolu sur le réseau interne de la pile, jamais une
    # adresse publique. Le défaut vaut pour l'exécution en conteneur ; hors Docker, SEARXNG_URL
    # doit pointer sur l'instance réellement joignable.
    searxng_url: str = Field(default=_URL_SEARXNG_DEFAUT, validation_alias="SEARXNG_URL")
    # Plus long que le `request_timeout` de SearXNG (4 s) : le service doit avoir le temps de
    # rendre ce qu'il a obtenu et de déclarer les moteurs muets, plutôt que d'être coupé avant.
    searxng_timeout_s: float = Field(default=8.0, gt=0, validation_alias="SEARXNG_TIMEOUT_S")

    # Atelier d'exécution : URL de service interne et jeton partagé. Le jeton n'est jamais codé en
    # dur ni journalisé — c'est le seul rempart devant un service qui exécute du shell root.
    atelier_url: str = Field(default=_URL_ATELIER_DEFAUT, validation_alias="ATELIER_URL")
    atelier_jeton: SecretStr | None = Field(default=None, validation_alias="ATELIER_JETON")
    # Relais d'aperçu de l'atelier, tel que le NAVIGATEUR l'atteint : l'app du projet y est servie.
    atelier_apercu_url: str = Field(default="http://127.0.0.1:37924", validation_alias="ATELIER_APERCU_URL")
    # Racine des PROJETS que l'on peut confier à une conversation (dossier de l'hôte, monté aussi
    # dans l'atelier sous /projets). Absente = mode projet désactivé, jamais une racine devinée.
    projets_racine: Path | None = Field(default=None, validation_alias="ECHOHUB_PROJETS_RACINE")

    @field_validator("data_home", mode="before")
    @classmethod
    def _ignorer_valeur_vide(cls, valeur: Any) -> Any:
        """Docker injecte parfois une variable vide : la traiter comme absente, pas comme `Path('.')`."""
        return valeur if valeur not in (None, "") else _racine_donnees_par_defaut()

    @field_validator("projets_racine", mode="before")
    @classmethod
    def _projets_vide_absent(cls, valeur: Any) -> Any:
        """Vide = désactivé : `Path('')` vaudrait le dossier courant, une racine que personne n'a choisie."""
        return valeur if valeur not in (None, "") else None

    @field_validator("models_dir", "engines_dir", "atelier_workspace", "agent_dir", mode="before")
    @classmethod
    def _deriver_de_data_home(cls, valeur: Any, info: Any) -> Any:
        """Un chemin non fourni tombe sous `data_home`, donc dans le volume persistant."""
        if valeur not in (None, ""):
            return valeur
        racine = info.data.get("data_home") or _racine_donnees_par_defaut()
        return Path(racine) / NOM_APPLICATION / _SOUS_DOSSIERS[info.field_name]

    @field_validator("searxng_url", mode="before")
    @classmethod
    def _normaliser_url_searxng(cls, valeur: Any) -> str:
        """Variable vide = absente (cf. `data_home`), et la barre finale est retirée une bonne fois.

        Sans cette normalisation, `http://searxng:8080/` produirait `//search` à la concaténation :
        une URL que certains serveurs acceptent, d'autres non — un défaut qui n'apparaîtrait qu'au
        premier appel réel, très loin de sa cause.
        """
        texte = str(valeur or "").strip()
        return (texte or _URL_SEARXNG_DEFAUT).rstrip("/")

    @field_validator("log_level", mode="before")
    @classmethod
    def _normaliser_niveau(cls, valeur: Any) -> str:
        niveau = str(valeur or "INFO").upper()
        if niveau not in _NIVEAUX_VALIDES:
            raise ValueError(f"Niveau de log inconnu : {niveau}. Valeurs admises : {sorted(_NIVEAUX_VALIDES)}")
        return niveau

    @property
    def data_dir(self) -> Path:
        """Répertoire applicatif : base de données, logs, caches."""
        return self.data_home / NOM_APPLICATION

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "echohub.db"

    def repertoires(self) -> tuple[Path, ...]:
        return (self.data_dir, self.logs_dir, self.models_dir, self.engines_dir)

    def preparer_repertoires(self) -> None:
        """Crée les répertoires nécessaires. Appelé avant toute écriture disque."""
        for chemin in self.repertoires():
            try:
                chemin.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logger.error("Création du répertoire {} impossible : {}", chemin, exc)
                raise ConfigurationInvalide(
                    f"Répertoire inutilisable : {chemin}",
                    remediation="Vérifier les droits d'écriture et le montage du volume correspondant.",
                    details={"chemin": str(chemin), "cause": str(exc)},
                ) from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Instance unique des réglages. Le cache évite de relire l'environnement à chaque appel."""
    return Settings()


def reset_settings_cache() -> None:
    """Vide le cache — réservé aux tests, qui modifient l'environnement entre deux cas."""
    get_settings.cache_clear()
