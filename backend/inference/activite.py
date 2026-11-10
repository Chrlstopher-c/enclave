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

from backend.outils.noms_publics import nom_interne, parametres_internes

INTERVALLE_S = 0.5
FENETRE_DEBIT_S = 3.0
OUTILS_GROUPES = frozenset({"ecrire_fichiers"})

_CHEMIN = re.compile(r'"(?:chemin|path)"\s*:\s*"((?:[^"\\]|\\.)*)"')
_DEBUT_LISTE = re.compile(r'"(?:fichiers|files)"\s*:\s*\[|<parameter=(?:fichiers|files)>\s*\[')
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


_PARAMETRE_XML = re.compile(r"<parameter=([\w.-]+)>\n?(.*?)(?:\n?</parameter>|\Z)", re.DOTALL)
_CLE_JSON = re.compile(r'"([\w.-]+)"\s*:\s*"')
APERCU_MAX = 6000


def _chaine_json_partielle(brut: str, debut: int) -> str:
    """Chaîne JSON commencée à `debut` (après le guillemet), décodée jusqu'à sa fin ou celle du texte."""
    morceaux, i = [], debut
    while i < len(brut):
        c = brut[i]
        if c == '"':
            break
        if c == "\\" and i + 1 < len(brut):
            suivant = brut[i + 1]
            if suivant == "u" and i + 5 < len(brut):
                try:
                    morceaux.append(chr(int(brut[i + 2:i + 6], 16)))
                except ValueError:
                    pass
                i += 6
                continue
            morceaux.append({"n": "\n", "t": "\t", "r": "", '"': '"', "\\": "\\", "/": "/"}.get(suivant, suivant))
            i += 2
            continue
        morceaux.append(c)
        i += 1
    return "".join(morceaux)


def parametres_partiels(brut: str) -> dict[str, str]:
    """Arguments déjà écrits d'un appel en cours, lisibles : XML `<parameter=…>` ou JSON partiel.

    Les valeurs longues ne gardent que leur FIN (`APERCU_MAX`) : l'écran montre ce qui s'écrit en ce moment.
    """
    valeurs: dict[str, str] = {}
    if "<parameter=" in brut:
        for nom, valeur in _PARAMETRE_XML.findall(brut):
            valeurs[nom] = valeur
    else:
        for trouve in _CLE_JSON.finditer(brut):
            valeurs.setdefault(trouve.group(1), _chaine_json_partielle(brut, trouve.end()))
    return {nom: valeur[-APERCU_MAX:] for nom, valeur in valeurs.items()}


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
        chemin, contenu = objet.get("chemin", objet.get("path")), objet.get("contenu", objet.get("content"))
        if isinstance(chemin, str) and isinstance(contenu, str):
            termines.append({"chemin": chemin, "contenu": contenu})


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
                     "fichiers_sauves": list(self.sauves),
                     "parametres": parametres_internes(self.outil, parametres_partiels(self.brut))[1]}
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
    nom = nom_interne(outil["nom"]) or outil["nom"]
    for fichier in suivi.appel(nom, brut):
        if ecrire is not None:
            await ecrire(fichier["chemin"], fichier["contenu"])


__all__ = [
    "INTERVALLE_S", "Ecriture", "SuiviActivite", "chemin_courant", "fichiers_termines", "parametres_partiels",
    "progression",
]
