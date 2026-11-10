"""Fichiers de travail : la dernière version connue de chaque fichier, reconstituée à partir des appels.

Demandé par Chris le 2026-11-10, pour la compaction : un fichier relu n'existe qu'une fois au contexte, dans
sa DERNIÈRE version lue ; ceux sur lesquels l'agent travaille juste avant la compaction restent sous ses
yeux, les plus lointains s'effacent les premiers. La version connue suit les gestes de l'agent :

- lecture (entière ou par plage) : une vue de ce passage, qui remplace la vue précédente du même passage ;
- écriture : le texte écrit devient l'unique vue du fichier, les lectures d'avant sont périmées ;
- modification : le fragment est remplacé dans les vues qui le contiennent ; sinon le fichier est marqué
  « modifié depuis », pour que l'agent sache qu'il doit le relire avant de s'y fier.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from backend.inference.engines_adapters.contrat import MessageChat

_PLAGE = re.compile(r"^\[lignes (\d+)-(\d+) sur (\d+)\]\n")
_ECHEC = ("Échec", "Failed", "Refused", "Same output as", "L'outil", "Commande refusée")


@dataclass
class Vue:
    """Un passage connu du fichier : le texte tel que l'agent l'a lu ou écrit."""

    debut: int
    texte: str
    entete: str = ""


@dataclass
class EtatFichier:
    chemin: str
    vues: dict[int, Vue] = field(default_factory=dict)
    dernier: int = 0
    modifie_depuis: bool = False

    def rendu(self) -> str:
        corps = "\n".join(f"{vue.entete}{vue.texte}" for _, vue in sorted(self.vues.items()))
        avis = " (edited since: re-read before relying on it)" if self.modifie_depuis else ""
        return f"### {self.chemin}{avis}\n{corps}"


def _arguments(appel: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    fonction = appel.get("function") or {}
    brut = fonction.get("arguments")
    try:
        arguments = json.loads(brut) if isinstance(brut, str) else (brut or {})
    except ValueError:
        arguments = {}
    return str(fonction.get("name", "")), arguments if isinstance(arguments, dict) else {}


def _lire(etat: EtatFichier, sortie: str) -> None:
    plage = _PLAGE.match(sortie)
    if plage is None:
        etat.vues = {1: Vue(1, sortie)}
    else:
        debut = int(plage.group(1))
        etat.vues[debut] = Vue(debut, sortie[plage.end():], plage.group(0))
    etat.modifie_depuis = False


def _modifier(etat: EtatFichier, ancien: str, nouveau: str) -> None:
    touche = False
    for vue in etat.vues.values():
        if ancien and ancien in vue.texte:
            vue.texte = vue.texte.replace(ancien, nouveau, 1)
            touche = True
    etat.modifie_depuis = etat.modifie_depuis or not touche


def _appliquer(fichiers: dict[str, EtatFichier], nom: str, arguments: dict[str, Any], sortie: str,
               rang: int) -> None:
    ecrits = arguments.get("fichiers") if nom == "ecrire_fichiers" else None
    if isinstance(ecrits, list):
        for item in ecrits:
            if isinstance(item, dict):
                _appliquer(fichiers, "ecrire_fichier", item, sortie, rang)
        return
    chemin = str(arguments.get("chemin") or "").strip()
    if not chemin or nom not in ("lire_fichier", "ecrire_fichier", "modifier_fichier"):
        return
    etat = fichiers.setdefault(chemin, EtatFichier(chemin))
    etat.dernier = rang
    if nom == "lire_fichier":
        _lire(etat, sortie)
    elif nom == "ecrire_fichier":
        etat.vues, etat.modifie_depuis = {1: Vue(1, str(arguments.get("contenu", "")))}, False
    else:
        _modifier(etat, str(arguments.get("ancien", "")), str(arguments.get("nouveau", "")))


def suivre(messages: Sequence[MessageChat]) -> dict[str, EtatFichier]:
    """Dernière version connue de chaque fichier touché par les appels de `messages`."""
    sorties = {m.tool_call_id: str(m.content) for m in messages if m.role == "tool" and m.tool_call_id}
    fichiers: dict[str, EtatFichier] = {}
    for rang, message in enumerate(messages):
        for appel in message.tool_calls or () if message.role == "assistant" else ():
            sortie = sorties.get(str(appel.get("id")))
            if sortie is None or sortie.startswith(_ECHEC):
                continue
            nom, arguments = _arguments(appel)
            _appliquer(fichiers, nom, arguments, sortie, rang)
    return fichiers


def selection(fichiers: dict[str, EtatFichier], budget: int, recents: str = "") -> list[EtatFichier]:
    """Les plus récents d'abord, tant que le budget (caractères) tient ; un fichier cité dans `recents`
    (le travail gardé mot pour mot) passe devant : c'est un fichier lié à ce que l'agent fait."""
    def priorite(etat: EtatFichier) -> tuple[bool, int]:
        nom = etat.chemin.rsplit("/", 1)[-1]
        return (nom in recents or nom.rsplit(".", 1)[0] in recents, etat.dernier)

    gardes: list[EtatFichier] = []
    for etat in sorted(fichiers.values(), key=priorite, reverse=True):
        taille = len(etat.rendu())
        if taille <= budget and etat.vues:
            gardes.append(etat)
            budget -= taille
    return gardes


__all__ = ["EtatFichier", "Vue", "selection", "suivre"]
