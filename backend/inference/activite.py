"""Activité en direct d'une génération : débit, phase, appel d'outil en cours, fichiers déjà sauvés.

Demandé par Chris le 2026-11-10 : l'agent écrivait une écriture groupée pendant plus de cinq minutes
sans rien montrer — carte graphique à 100 %, écran muet, aucun fichier sur le disque. Tout était
perdu au moindre plantage, et rien ne distinguait « il travaille » de « il est bloqué ».

Ce module ne décide de rien : il tient les compteurs, lit l'appel d'outil EN COURS d'écriture
(`brut` : arguments JSON partiels, ou XML `<parameter=…>` brut selon le moteur) et rend, au plus
toutes les `INTERVALLE_S`, un instantané que le chat diffuse. Les fichiers d'une écriture groupée
déjà complets dans `brut` sont rendus une fois chacun, pour être écrits sans attendre la fin.
"""

from __future__ import annotations

import json
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

INTERVALLE_S = 0.5
FENETRE_DEBIT_S = 3.0
OUTILS_GROUPES = frozenset({"ecrire_fichiers"})

_CHEMIN = re.compile(r'"chemin"\s*:\s*"((?:[^"\\]|\\.)*)"')
_DEBUT_LISTE = re.compile(r'"fichiers"\s*:\s*\[|<parameter=fichiers>\s*\[')
_DECODEUR = json.JSONDecoder()

# Écrit un fichier d'une écriture groupée dès qu'il est complet ; le harnais la fournit (outil réel).
Ecriture = Callable[[str, str], Awaitable[None]]


def chemin_courant(brut: str) -> str | None:
    """Dernier `chemin` déjà écrit dans les arguments partiels : le fichier en cours."""
    trouves = _CHEMIN.findall(brut)
    if not trouves:
        return None
    try:
        return str(json.loads(f'"{trouves[-1]}"'))
    except json.JSONDecodeError:
        return trouves[-1]


def fichiers_termines(brut: str) -> list[dict[str, str]]:
    """Objets `{chemin, contenu}` COMPLETS de la liste `fichiers`, dans l'ordre ; le dernier, partiel, est exclu."""
    debut = _DEBUT_LISTE.search(brut)
    if debut is None:
        return []
    position, termines = debut.end(), []
    while True:
        while position < len(brut) and brut[position] in " \t\r\n,":
            position += 1
        if position >= len(brut) or brut[position] != "{":
            return termines
        try:
            objet, position = _DECODEUR.raw_decode(brut, position)
        except json.JSONDecodeError:
            return termines
        if isinstance(objet, dict) and isinstance(objet.get("chemin"), str) and isinstance(objet.get("contenu"), str):
            termines.append({"chemin": objet["chemin"], "contenu": objet["contenu"]})


@dataclass
class SuiviActivite:
    """Compteurs d'une génération (tous tours confondus) et appel d'outil en cours d'écriture."""

    jetons: int = 0
    phase: str = "texte"
    outil: str | None = None
    brut: str = ""
    sauves: list[str] = field(default_factory=list)
    taches: list[dict[str, str]] | None = None
    _horodatages: deque[tuple[float, int]] = field(default_factory=deque)
    _dernier_envoi: float = 0.0
    _dans_reflexion: bool = False
    _progression_vue: bool = False

    def compter(self, nombre: int, *, progression: bool) -> None:
        """Jetons générés. Un moteur qui envoie des `progression` est compté par elles seules."""
        if progression:
            self._progression_vue = True
        elif self._progression_vue:
            return
        maintenant = time.monotonic()
        self.jetons += nombre
        self._horodatages.append((maintenant, nombre))
        while self._horodatages and maintenant - self._horodatages[0][0] > FENETRE_DEBIT_S:
            self._horodatages.popleft()

    def texte(self, fragment: str) -> None:
        """Texte visible : suit l'ouverture et la fermeture du raisonnement pour nommer la phase."""
        if "<think>" in fragment:
            self._dans_reflexion = True
        if "</think>" in fragment:
            self._dans_reflexion = False
        if self.outil is None:
            self.phase = "reflexion" if self._dans_reflexion else "texte"

    def appel(self, nom: str, brut: str) -> list[dict[str, str]]:
        """Appel en cours d'écriture ; rend les fichiers d'une écriture groupée devenus complets."""
        self.outil, self.brut, self.phase = nom, brut, "outil"
        if nom not in OUTILS_GROUPES:
            return []
        nouveaux = fichiers_termines(brut)[len(self.sauves):]
        self.sauves.extend(fichier["chemin"] for fichier in nouveaux)
        return nouveaux

    def execution(self, nom: str) -> None:
        """Un outil s'exécute : le moteur ne génère rien, et c'est normal — l'écran doit le dire."""
        self.outil, self.brut, self.phase = nom, "", "execution"

    def fin_de_tour(self) -> None:
        """Le tour du moteur est clos : l'appel en cours, s'il y en avait un, part à l'exécution."""
        self.outil, self.brut, self.sauves = None, "", []
        self.phase = "reflexion" if self._dans_reflexion else "texte"

    def debit(self) -> float:
        if len(self._horodatages) < 2:
            return 0.0
        duree = self._horodatages[-1][0] - self._horodatages[0][0]
        return round(sum(n for _, n in list(self._horodatages)[1:]) / duree, 1) if duree > 0 else 0.0

    def instantane(self, *, force: bool = False) -> dict[str, Any] | None:
        """État à diffuser, au plus toutes les `INTERVALLE_S` sauf si `force`."""
        maintenant = time.monotonic()
        if not force and maintenant - self._dernier_envoi < INTERVALLE_S:
            return None
        self._dernier_envoi = maintenant
        outil = None
        if self.outil is not None:
            outil = {"nom": self.outil, "chemin": chemin_courant(self.brut), "caracteres": len(self.brut),
                     "fichiers_sauves": list(self.sauves)}
        return {"phase": self.phase, "tokens": self.jetons, "tokens_par_seconde": self.debit(),
                "outil": outil, "taches": self.taches}


async def progression(suivi: SuiviActivite, details: dict[str, Any], ecrire: Ecriture | None) -> None:
    """Applique un morceau `progression` du moteur ; écrit aussitôt les fichiers groupés devenus complets."""
    jetons = details.get("jetons")
    suivi.compter(int(jetons) if isinstance(jetons, int) else 1, progression=True)
    outil = details.get("outil")
    if not isinstance(outil, dict) or not isinstance(outil.get("nom"), str) or not outil["nom"]:
        return
    brut = outil.get("brut") if isinstance(outil.get("brut"), str) else ""
    for fichier in suivi.appel(outil["nom"], brut):
        if ecrire is not None:
            await ecrire(fichier["chemin"], fichier["contenu"])


__all__ = ["INTERVALLE_S", "Ecriture", "SuiviActivite", "chemin_courant", "fichiers_termines", "progression"]
