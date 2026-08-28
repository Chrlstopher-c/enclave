"""Contrat que `chat` attend du domaine `inference` — défini ici, côté consommateur.

C'est le seul point de contact entre les deux domaines. `chat` n'importe aucun interne
d'`inference` : il déclare la forme minimale dont il a besoin (un itérateur asynchrone de
fragments) et la couche d'assemblage y branche l'implémentation réelle via `definir_moteur`.

Deux conséquences voulues :
- `chat` est testable sans GPU ni moteur — un faux moteur de dix lignes suffit ;
- un changement interne d'`inference` ne casse `chat` que s'il casse ce contrat, qui tient en un
  fichier lisible.

Contrat attendu de l'implémentation :

    class MonMoteur:
        def generer(self, requete: RequeteGeneration) -> AsyncIterator[ElementFlux]: ...

`generer` retourne l'itérateur SANS être une coroutine (pas d'`await` pour l'obtenir), et rend des
`FragmentTexte` au fil de la génération, éventuellement suivis d'un `StatistiquesGeneration`.
Fermer l'itérateur (`aclose`) doit interrompre la génération côté moteur : c'est ainsi que `chat`
annule proprement.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from backend.core import MoteurIndisponible
from backend.chat.modeles import ParametresEchantillonnage, RoleMessage


class PieceJointe(BaseModel):
    """Référence à un fichier de conversation, telle qu'elle traverse le port `chat` → `inference`.

    Transporte un CHEMIN, jamais des octets ni du base64 (plan d'exécution, section 2.2.2) : ce
    port est traversé à chaque tour de génération, y faire voyager des mégaoctets encodés serait
    payé à chaque tour. L'encodage en data URI n'a lieu qu'au tout dernier moment, dans l'adaptateur
    moteur, juste avant l'appel réel au moteur.
    """

    model_config = ConfigDict(extra="forbid")

    chemin: Path
    type_mime: str
    nom_affiche: str


class MessageInference(BaseModel):
    """Message tel qu'il part au moteur : ni identifiant, ni horodatage, ni statistiques."""

    model_config = ConfigDict(extra="forbid")

    role: RoleMessage
    contenu: str
    pieces: list[PieceJointe] = Field(default_factory=list)


class RequeteGeneration(BaseModel):
    """Tout ce dont le moteur a besoin pour produire un tour, et rien de plus.

    `modele_id` est indicatif : le chargement des modèles appartient à `inference`. `chat` dit sur
    quel modèle la conversation travaille, il ne décide pas comment le charger.

    `conversation_id` est obligatoire : c'est l'identité qui doit atteindre l'exécution d'un outil
    (plan d'exécution, section 2.5). Sans elle, un outil confiné ne saurait dans quel bac écrire.
    """

    model_config = ConfigDict(extra="forbid")

    messages: list[MessageInference] = Field(min_length=1)
    parametres: ParametresEchantillonnage
    modele_id: str | None = None
    conversation_id: str = Field(min_length=1)


class OccupationContexte(BaseModel):
    """Ce que `chat` a besoin de savoir de l'occupation de la fenêtre, côté consommateur.

    Forme minimale — un sous-ensemble de ce que le domaine `inference` mesure : `chat` n'a besoin
    ici que du taux d'occupation, jamais de la décomposition par poste. `mesurable` faux n'est pas
    une erreur : c'est l'absence de tokenizer (aucun modèle prêt, moteur occupé), et les champs
    chiffrés restent alors à `None` — un zéro se lirait comme une fenêtre libre et déciderait à tort
    de compacter, ou de ne pas le faire.
    """

    model_config = ConfigDict(extra="forbid")

    mesurable: bool
    contexte_total: int | None = None
    tokens_mesures: int | None = None
    tokens_libres: int | None = None


class FragmentTexte(BaseModel):
    """Morceau de texte produit par le moteur."""

    model_config = ConfigDict(extra="forbid")

    texte: str


class StatistiquesGeneration(BaseModel):
    """Mesures rapportées par le moteur en fin de génération.

    Les deux champs sont facultatifs : un moteur qui ne compte pas ses tokens laisse `None`, et
    `chat` persiste `None`. Aucune estimation de substitution — c'est le défaut central de la v1.
    """

    model_config = ConfigDict(extra="forbid")

    tokens_generes: int | None = Field(default=None, ge=0)
    tokens_par_seconde: float | None = Field(default=None, ge=0)


ElementFlux = FragmentTexte | StatistiquesGeneration


@runtime_checkable
class MoteurGeneration(Protocol):
    """Interface minimale consommée par `chat`."""

    def generer(self, requete: RequeteGeneration) -> AsyncIterator[ElementFlux]:
        """Ouvre un flux de génération. L'itérateur rendu est fermé par `chat` à l'annulation."""
        ...

    async def mesurer_occupation(self, messages: Sequence[MessageInference]) -> OccupationContexte:
        """Occupation de la fenêtre pour CES messages tels qu'ils partiraient au moteur.

        Sert la décision de compaction : `chat` construit ce qui irait au moteur et demande combien
        de tokens il pèse, sans lancer de génération. Une mesure absente (`mesurable=False`) ne
        déclenche rien — c'est la même discipline que partout, une absence ne décide de rien.
        """
        ...

    async def resumer(
        self, a_resumer: str, resume_precedent: str, langue: str, max_tokens: int
    ) -> str | None:
        """Résumé cumulatif orienté agent des tours anciens, produit par le modèle chargé.

        `resume_precedent` est le résumé d'une compaction antérieure, à ENGLOBER et non à oublier.
        Rend `None` si le résumé ne peut pas être produit (aucun modèle prêt, échec moteur) : la
        compaction est alors abandonnée plutôt que de tronquer sans filet.
        """
        ...


# Moteur courant du processus. État partagé assumé et confiné : le flux HTTP est sans état, mais
# le moteur, lui, est unique pour toute l'application (le GPU est une ressource exclusive).
_moteur: MoteurGeneration | None = None


def definir_moteur(moteur: MoteurGeneration) -> None:
    """Branche l'implémentation réelle. Appelé une fois au démarrage, ou par un test."""
    global _moteur
    _moteur = moteur
    logger.info("Moteur de génération branché sur le domaine chat : {}", type(moteur).__name__)


def reinitialiser_moteur() -> None:
    """Débranche le moteur — réservé aux tests, qui ne doivent pas hériter du cas précédent."""
    global _moteur
    _moteur = None


def obtenir_moteur() -> MoteurGeneration:
    """Retourne le moteur branché, ou tente de le résoudre depuis le domaine `inference`."""
    global _moteur
    if _moteur is not None:
        return _moteur

    # Import tardif : `adaptation_inference` dépend des types définis ci-dessus, l'importer en tête
    # de module créerait un cycle.
    from backend.chat.adaptation_inference import resoudre_moteur

    resolu = resoudre_moteur()
    if resolu is None:
        raise MoteurIndisponible(
            "Aucun moteur de génération n'est branché sur le domaine chat.",
            remediation=(
                "Appeler chat.definir_moteur(...) au démarrage, ou exposer creer_moteur_chat() "
                "dans l'interface publique du domaine inference."
            ),
        )
    _moteur = resolu
    return resolu
