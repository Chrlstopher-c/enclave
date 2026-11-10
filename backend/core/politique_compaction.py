"""Quand compacter le contexte — la règle de Quart, partagée par `chat` et `inference`.

Pure, sans I/O. Compacter coûte un retraitement complet du prompt (sur la tour : ~245 tok/s, donc une
pause de plusieurs dizaines de secondes) : on ne le fait qu'à une fin d'étape déjà lourde, ou quand le
contexte devient cher à relire à chaque tour. Jamais « pour rien ».

- seuil d'ÉTAPE : à une frontière naturelle (fin d'une tâche, nouveau message), au-delà de
  min(120 k, 70 % de la fenêtre) ;
- seuil DUR : à n'importe quelle fin de tour d'outil, au-delà de min(350 k, 80 % de la fenêtre).

Réglé le 2026-11-10 avec Chris (Ornith 9B, fenêtre 64K) : 40 % / 70 % compactait trop souvent, et chaque
résumé perd du détail. La RÉSERVE de 20 % au-dessus du seuil dur couvre le tour suivant, même une grosse
écriture de fichier (10-15K tokens) ; en dessous, un tour pouvait déborder avant la compaction suivante.

L'ancienne règle (90 % de la fenêtre servie) attendait ~236 k tokens sur une fenêtre de 262 k : elle ne
se déclenchait jamais avant qu'une tâche d'agent ne bute sur « fenêtre pleine » (2026-10-02).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ETAPE_PLAFOND = 120_000
DUR_PLAFOND = 350_000
ETAPE_FRACTION = 0.70
DUR_FRACTION = 0.80
# Après compaction, la queue gardée mot pour mot (fichiers de travail compris) tient sous cette fraction
# de la FENÊTRE : le contexte retombe vers 45 %, ce qui laisse ~35 % de travail avant la suivante.
QUEUE_FRACTION_FENETRE = 0.30

# Taille FIXE de ce qu'une compaction réinjecte, auto ou manuelle (Chris, 2026-11-10) : au plus 10K tokens,
# quelle que soit la fenêtre — résumé 4K, dernières consignes mot pour mot 2K, fichiers de travail 4K.
RESUME_MAX_TOKENS = 4_000
DIRECTIVES_MAX_TOKENS = 2_000
FICHIERS_MAX_TOKENS = 4_000
COMPACTION_MAX_TOKENS = RESUME_MAX_TOKENS + DIRECTIVES_MAX_TOKENS + FICHIERS_MAX_TOKENS

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
    return min(int(fenetre * QUEUE_FRACTION_FENETRE), seuils_pour(fenetre).etape // 2)


__all__ = [
    "COMPACTION_MAX_TOKENS", "DIRECTIVES_MAX_TOKENS", "FICHIERS_MAX_TOKENS", "RESUME_MAX_TOKENS", "Raison", "Seuils",
    "budget_queue", "decider", "seuils_pour",
]
