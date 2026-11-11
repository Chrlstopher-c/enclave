"""Progression d'une commande : l'état lisible à chaque instant, et ce qui le fait avancer.

Trois pièces : le compteur d'une compaction (`ProgressionCompaction`, alimenté par les rappels `suivi`
des fonctions de compaction), l'état d'une commande qui le porte (`EtatCommande`), et le battement qui
rend la main au moins une fois par seconde tant qu'un travail tourne (`battements`). Aucun import du
domaine `chat` : le module se lit seul.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from backend.core import maintenant

INTERVALLE_BATTEMENT_S = 1.0
ETAPES: tuple[tuple[str, str], ...] = (
    ("preparation", "Préparation"),
    ("resume", "Résumé"),
    ("enregistrement", "Enregistrement"),
)


@dataclass
class ProgressionCompaction:
    """Où en est un résumé : étape, résumeur, débit (résumé local seulement). Une instance par compaction."""

    etape: str = "preparation"
    detail: str = ""
    resumeur: str | None = None
    tokens: int | None = None
    tokens_par_seconde: float | None = None
    demarree: bool = False
    _debut: float = field(default_factory=time.monotonic)
    _fin: float | None = None

    def appliquer(self, details: Mapping[str, Any]) -> None:
        """Retient ce que le rappel vient de dire ; une clé absente ne change rien."""
        self.demarree = True
        if "etape" in details:
            self.etape = str(details["etape"])
        if "detail" in details:
            self.detail = str(details["detail"])
        if "resumeur" in details:
            self.resumeur = details["resumeur"]
        if "tokens" in details:
            self.tokens = details["tokens"]
        if "tokens_par_seconde" in details:
            self.tokens_par_seconde = details["tokens_par_seconde"]

    def figer(self) -> None:
        self._fin = time.monotonic()

    def duree_ms(self) -> int:
        fin = self._fin if self._fin is not None else time.monotonic()
        return max(0, round((fin - self._debut) * 1000))

    def comme_dict(self) -> dict[str, Any]:
        return {
            "etape": self.etape,
            "detail": self.detail,
            "resumeur": self.resumeur,
            "tokens": self.tokens,
            "tokens_par_seconde": self.tokens_par_seconde,
            "duree_ms": self.duree_ms(),
        }


def activite_compaction(progression: ProgressionCompaction) -> dict[str, Any]:
    """Le contenu d'un `EvenementActivite` pendant une compaction automatique : phase `compaction`."""
    return {"phase": "compaction", "compaction": progression.comme_dict()}


@dataclass
class EtatCommande:
    """Une commande en cours ou finie : son identité, sa progression, son état et sa fin de message."""

    id: str
    nom: str
    progression: ProgressionCompaction = field(default_factory=ProgressionCompaction)
    etat: str = "en_cours"
    debut: str = field(default_factory=maintenant)
    erreur: str | None = None

    def terminer(self) -> None:
        self.etat = "termine"
        self.progression.etape = "enregistrement"
        self.progression.figer()

    def echouer(self, message: str) -> None:
        self.etat = "echec"
        self.erreur = message
        self.progression.figer()

    def snapshot(self) -> dict[str, Any]:
        """La charge `commande` de l'événement, telle que le contrat la décrit."""
        progression = self.progression
        return {
            "id": self.id,
            "nom": self.nom,
            "etat": self.etat,
            "etape": progression.etape,
            "etapes": self._etapes(),
            "detail": progression.detail,
            "resumeur": progression.resumeur,
            "tokens": progression.tokens,
            "tokens_par_seconde": progression.tokens_par_seconde,
            "moteur": None,
            "debut": self.debut,
            "duree_ms": progression.duree_ms(),
            "erreur": self.erreur,
        }

    def _etapes(self) -> list[dict[str, str]]:
        courant = next((i for i, (cle, _) in enumerate(ETAPES) if cle == self.progression.etape), 0)
        rendu: list[dict[str, str]] = []
        for i, (cle, libelle) in enumerate(ETAPES):
            if self.etat == "termine" or i < courant:
                etat = "fait"
            elif i == courant:
                etat = "en_cours"
            else:
                etat = "a_faire"
            rendu.append({"cle": cle, "libelle": libelle, "etat": etat})
        return rendu


async def battements(tache: asyncio.Future[Any]) -> AsyncIterator[None]:
    """Rend la main au plus toutes les `INTERVALLE_BATTEMENT_S` secondes tant que `tache` tourne.

    L'appelant publie son état à chaque tour de boucle : c'est ce qui fait avancer la durée côté écran.
    """
    while True:
        await asyncio.wait({tache}, timeout=INTERVALLE_BATTEMENT_S)
        if tache.done():
            return
        yield None
