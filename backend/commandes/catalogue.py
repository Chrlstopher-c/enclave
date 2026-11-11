"""Catalogue des commandes du chat : ce que `GET /chat/commandes` annonce, et ce que l'exécution accepte.

Le nom est la clé (`compact`, `clear`) ; le navigateur envoie `/compact` et la route retire le slash.
Ajouter une commande : une ligne ici, une branche dans `execution.lancer`.
"""

from __future__ import annotations

from pydantic import BaseModel

from backend.core import EchoHubError


class CommandeDisponible(BaseModel):
    nom: str
    usage: str
    description: str
    arguments: bool


class CommandeInvalide(EchoHubError):
    """Commande connue, mais demandée dans une forme qu'elle n'accepte pas (arguments en trop, etc.)."""

    code = "commande_invalide"
    statut_http = 422
    remediation_defaut = "Vérifier la forme de la commande (`/clear` n'attend aucun argument)."


CATALOGUE: tuple[CommandeDisponible, ...] = (
    CommandeDisponible(
        nom="compact",
        usage="/compact [instructions]",
        description="Résume le contexte de la conversation pour libérer de la place. "
        "Les instructions disent quoi garder en priorité.",
        arguments=True,
    ),
    CommandeDisponible(
        nom="clear",
        usage="/clear",
        description="Repart d'un contexte vierge dans cette conversation. Annulable : « Revenir à l'état précédent ».",
        arguments=False,
    ),
)


def commande_connue(nom: str) -> CommandeDisponible | None:
    return next((commande for commande in CATALOGUE if commande.nom == nom), None)
