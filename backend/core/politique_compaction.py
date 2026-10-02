"""Quand compacter le contexte — la règle de Quart, partagée par `chat` et `inference`.

Pure, sans I/O. Compacter coûte un retraitement complet du prompt (sur la tour : ~245 tok/s, donc une
pause de plusieurs dizaines de secondes) : on ne le fait qu'à une fin d'étape déjà lourde, ou quand le
contexte devient cher à relire à chaque tour. Jamais « pour rien ».

- seuil d'ÉTAPE : à une frontière naturelle (fin d'une tâche, nouveau message), au-delà de
  min(120 k, 40 % de la fenêtre) ;
- seuil DUR : à n'importe quelle fin de tour d'outil, au-delà de min(350 k, 70 % de la fenêtre).

L'ancienne règle (90 % de la fenêtre servie) attendait ~236 k tokens sur une fenêtre de 262 k : elle ne
se déclenchait jamais avant qu'une tâche d'agent ne bute sur « fenêtre pleine » (2026-10-02).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ETAPE_PLAFOND = 120_000
DUR_PLAFOND = 350_000
ETAPE_FRACTION = 0.40
DUR_FRACTION = 0.70
# Après compaction, la queue gardée mot pour mot tient sous cette fraction du seuil d'étape : assez
# bas pour ne pas re-déclencher au tour suivant, assez haut pour garder le fil récent intact.
QUEUE_FRACTION_DU_SEUIL = 0.50

Raison = Literal["etape", "seuil"]


@dataclass(frozen=True)
class Seuils:
    etape: int
    dur: int


def seuils_pour(fenetre: int) -> Seuils:
    return Seuils(etape=min(ETAPE_PLAFOND, round(fenetre * ETAPE_FRACTION)),
                  dur=min(DUR_PLAFOND, round(fenetre * DUR_FRACTION)))


def decider(contexte: int, fenetre: int, etape_terminee: bool) -> Raison | None:
    """`seuil`, `etape`, ou `None` pour ne rien faire."""
    seuils = seuils_pour(fenetre)
    if contexte >= seuils.dur:
        return "seuil"
    if etape_terminee and contexte >= seuils.etape:
        return "etape"
    return None


def budget_queue(fenetre: int) -> int:
    """Tokens que la queue conservée mot pour mot peut occuper après une compaction."""
    return int(seuils_pour(fenetre).etape * QUEUE_FRACTION_DU_SEUIL)


__all__ = ["Raison", "Seuils", "budget_queue", "decider", "seuils_pour"]
