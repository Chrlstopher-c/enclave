"""Budget de réflexion par tour de la boucle d'outils — la réflexion raccourcie, jamais coupée.

Mesuré le 2026-11-11 : le 35B réfléchissait 5 000 à 9 000 caractères après des appels RÉUSSIS, et le 9B a
passé 11 min dans un seul bloc de réflexion sans un appel (simulation mentale de son code). Le budget suit
ce que le tour a à faire : planifier au départ, comprendre un échec, ou juste enchaîner après un succès.
Le moteur clôt la réflexion au plafond par un message « act now » (`sobriete_reflexion`).

Resserré après le run « Tetris test 35B budget » (2048 / 768 / 1536 / 1024) : le plafond ne s'était
déclenché que 2 fois sur 56 appels, la réflexion pesait encore ~45 % des tokens générés, et le premier tour
en faisait 7 000 caractères. Après un succès, la suite est presque toujours déjà décidée.
"""

from __future__ import annotations

from backend.inference.engines_adapters.contrat import OptionsGeneration

BUDGET_PREMIER_TOUR = 1536
BUDGET_APRES_SUCCES = 384
BUDGET_APRES_ECHEC = 1024
BUDGET_RELANCE = 768

_BUDGETS = {"debut": BUDGET_PREMIER_TOUR, "succes": BUDGET_APRES_SUCCES, "echec": BUDGET_APRES_ECHEC}


def options_du_tour(options: OptionsGeneration, issue_precedente: str) -> OptionsGeneration:
    """Les options du prochain tour : budget selon l'issue du tour précédent, hésitations bannies."""
    budget = _BUDGETS.get(issue_precedente, BUDGET_RELANCE)
    return options.model_copy(update={"budget_reflexion": budget, "bannir_hesitations": True})
