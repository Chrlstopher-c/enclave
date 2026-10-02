"""Outil `suivre_taches` — la liste de tâches de l'agent, tenue à jour au fil du travail.

Demandé par Chris le 2026-10-02 : « quand il dit qu'il va faire des choses, il doit vraiment les
faire ». Une annonce en prose ne se vérifie pas ; une liste, si. Le modèle écrit son plan, passe une
tâche `en_cours`, la marque `fait` une fois vérifiée — et le harnais refuse de clore le tour tant
qu'une tâche reste ouverte (`taches_ouvertes`, lu par `inference`).

La liste est remplacée EN ENTIER à chaque appel (même contrat que l'outil équivalent de Claude Code) :
aucun état partiel à réconcilier, le modèle renvoie toujours la vérité complète.
Gardée en mémoire par conversation : elle sert pendant la génération, un redémarrage peut l'oublier.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from backend.outils.contrat import ContexteExecution, DescriptionOutil, EchecOutil, Outil

TACHES_MAX = 30


# `str, Enum` plutôt que `StrEnum` (3.11+) : l'image Docker tourne en Python 3.10.
class EtatTache(str, Enum):
    A_FAIRE = "a_faire"
    EN_COURS = "en_cours"
    FAIT = "fait"
    BLOQUE = "bloque"
    ABANDONNE = "abandonne"


OUVERTS = frozenset({EtatTache.A_FAIRE, EtatTache.EN_COURS})
_EXIGE_RAISON = frozenset({EtatTache.BLOQUE, EtatTache.ABANDONNE})
_CASE = {EtatTache.A_FAIRE: "[ ]", EtatTache.EN_COURS: "[>]", EtatTache.FAIT: "[x]",
         EtatTache.BLOQUE: "[!]", EtatTache.ABANDONNE: "[-]"}


class Tache(BaseModel):
    titre: str = Field(min_length=1, max_length=200)
    etat: EtatTache = EtatTache.A_FAIRE
    raison: str = Field(default="", max_length=300)
    # Ce qui PROUVE qu'une tâche est faite (« pytest -q : 9 passed », « curl /api/notes → 200 »).
    # Exigée au passage à `fait` : le 2026-10-02 le modèle marquait tout fait pour sortir d'une relance,
    # sans rien avoir exécuté. Le harnais ne juge pas la vérité, mais une preuve se lit et se vérifie.
    preuve: str = Field(default="", max_length=300)


_LISTES: dict[str, list[Tache]] = {}

DESCRIPTION = DescriptionOutil(
    nom="suivre_taches",
    description=(
        "Your task list for the current request, replaced in full at each call. For any request of "
        "more than two steps, call it FIRST with your plan, then again whenever an item CHANGES: one "
        "item `en_cours` at a time; `fait` only once a command proved it, and that item needs `preuve` "
        "(the check and its result, e.g. `pytest -q: 9 passed`). Never mark an item `fait` to end a turn: "
        "do it first. Only WORK items go in the list — not « reply to the user ». The harness will not "
        "let your turn end while an item is `a_faire` or `en_cours` — finish it, or mark it `bloque` "
        "(needs the user: put the question in `raison`) or `abandonne` (with the reason)."
    ),
    parametres={
        "type": "object",
        "properties": {
            "taches": {
                "type": "array",
                "description": "The FULL list, in order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "titre": {"type": "string", "description": "What this step delivers, in a few words."},
                        "etat": {"type": "string", "enum": [e.value for e in EtatTache]},
                        "raison": {"type": "string", "description": "Required for `bloque` and `abandonne`."},
                        "preuve": {"type": "string",
                                   "description": "Required when an item becomes `fait`: the check that proved it."},
                    },
                    "required": ["titre", "etat"],
                },
            },
        },
        "required": ["taches"],
    },
    alias={alias: "taches" for alias in ("todos", "tasks", "liste", "plan", "items")},
)


def _verifier_transitions(avant: list[Tache], apres: list[Tache]) -> None:
    """Refuse une liste inchangée (boucle) et un passage à `fait` sans preuve."""
    if avant and [(t.titre, t.etat) for t in avant] == [(t.titre, t.etat) for t in apres]:
        raise EchecOutil(
            "Échec : liste inchangée. N'appelle `suivre_taches` que quand une tâche CHANGE. Si tout est "
            "fait, écris maintenant ta réponse finale à l'utilisateur, sans autre appel.")
    deja_faites = {t.titre for t in avant if t.etat == EtatTache.FAIT}
    sans_preuve = [t.titre for t in apres
                   if t.etat == EtatTache.FAIT and t.titre not in deja_faites and not t.preuve.strip()]
    if sans_preuve:
        raise EchecOutil(
            f"Échec : {sans_preuve} passe(nt) à `fait` sans `preuve`. Indique la vérification qui le prouve "
            "(commande et résultat). Si tu ne l'as pas encore faite, laisse la tâche `en_cours` et fais-la.")


def _lire(arguments: dict[str, Any]) -> list[Tache]:
    brut = DESCRIPTION.normaliser(arguments).get("taches")
    if isinstance(brut, str):
        try:
            brut = json.loads(brut)
        except json.JSONDecodeError as exc:
            raise EchecOutil(f"Échec : `taches` n'est pas une liste JSON lisible ({exc}).") from exc
    if not isinstance(brut, list) or len(brut) > TACHES_MAX:
        raise EchecOutil(f"Échec : `taches` attend la liste COMPLÈTE des tâches ({TACHES_MAX} au plus).")
    try:
        taches = [Tache.model_validate(t) for t in brut]
    except ValidationError as exc:
        raise EchecOutil(f"Échec : tâche invalide — {exc.errors()[0]['msg']}. États permis : "
                         f"{', '.join(e.value for e in EtatTache)}.") from exc
    sans_raison = [t.titre for t in taches if t.etat in _EXIGE_RAISON and not t.raison.strip()]
    if sans_raison:
        raise EchecOutil(f"Échec : `raison` obligatoire pour une tâche bloquée ou abandonnée : {sans_raison}.")
    return taches


def rendre(taches: list[Tache]) -> str:
    faites = sum(t.etat == EtatTache.FAIT for t in taches)
    lignes = [f"{_CASE[t.etat]} {t.titre}" + (f" — {t.raison}" if t.raison else "")
              + (f" — preuve : {t.preuve}" if t.preuve and t.etat == EtatTache.FAIT else "") for t in taches]
    return f"Tâches ({faites}/{len(taches)} faites) :\n" + "\n".join(lignes)


async def _executer(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
    taches = _lire(arguments)
    _verifier_transitions(_LISTES.get(contexte.conversation_id, []), taches)
    _LISTES[contexte.conversation_id] = taches
    en_cours = sum(t.etat == EtatTache.EN_COURS for t in taches)
    logger.info("Tâches de {} : {} dont {} ouverte(s).", contexte.conversation_id, len(taches),
                len(taches_ouvertes(contexte.conversation_id)))
    avis = "\nNote : une seule tâche `en_cours` à la fois." if en_cours > 1 else ""
    return rendre(taches) + avis


def taches_ouvertes(conversation_id: str) -> list[str]:
    """Titres des tâches encore à faire ou en cours pour cette conversation."""
    return [t.titre for t in _LISTES.get(conversation_id, []) if t.etat in OUVERTS]


def liste_taches(conversation_id: str) -> str:
    """La liste rendue telle que le modèle l'a vue, ou chaîne vide : réinjectée dans un résumé de compaction."""
    taches = _LISTES.get(conversation_id)
    return rendre(taches) if taches else ""


OUTIL = Outil(description=DESCRIPTION, executer=_executer)

__all__ = ["OUTIL", "TACHES_MAX", "EtatTache", "Tache", "liste_taches", "rendre", "taches_ouvertes"]
