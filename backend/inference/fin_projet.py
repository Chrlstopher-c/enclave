"""Mode projet : dire si un tour sans appel d'outil est une vraie fin de travail ou une pause.

Deux façons, mesurées le 2026-10-01 sur le 35B, de rendre la main trop tôt :
- la pause courte : « Je dois réinstaller les dépendances dans le venv correctement. » (95 car.) ;
- le faux bilan : un rapport soigné dont la section « Ce qui reste à faire » donne la commande
  à lancer (`rm -f todos.db && .venv/bin/pytest`) et le serveur à démarrer — du travail que le
  modèle pouvait faire lui-même, rendu à l'utilisateur avec 3 tests verts sur 9.
"""

from __future__ import annotations

import re

# Sous cette longueur (raisonnement retiré), un texte sans appel n'est pas un bilan : un bilan réel
# (construit, lancé, vérifié, reste) dépasse 400 caractères.
BILAN_PROJET_MIN_CARACTERES = 400
# Le faux bilan a droit à peu de relances, sans réarmement : un reste qui dépend vraiment de
# l'utilisateur (une clé d'API, un choix) ne doit pas faire tourner la boucle.
RELANCES_RESTE_MAX = 2

_RAISONNEMENT = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL)
_SECTION_RESTE = re.compile(
    r"reste[rs]? (?:à|a) faire|il (?:me |nous )?reste|restant|prochaines? étapes?|"
    r"remaining|still (?:to do|needed)|next steps?|to ?do\b",
    re.IGNORECASE,
)
_ACTION_FAISABLE = re.compile(
    r"```(?:bash|sh|shell|console)?\n|`serveur_fond`|\bcurl\b|\bpytest\b|\bbun (?:run|test|install)\b|"
    r"lancer le serveur|start the server|run the tests",
    re.IGNORECASE,
)

CONSIGNE_SUITE_PROJET = (
    "You stopped without calling a tool, and what you wrote is not a final report. You are working "
    "on the project: call the next tool NOW (run the command, write the file). Only if the whole "
    "task is really finished, write the final report instead: what was built, how to run it, what "
    "you actually verified, and what remains."
)

CONSIGNE_RESTE_FAISABLE = (
    "Your report lists remaining work that you can do yourself with your tools (a command to run, "
    "tests to fix, a server to start and check with curl). Do not hand it to the user: do it NOW, "
    "starting with a tool call in this turn. Only items that truly need the user (a secret, a "
    "decision) may stay in the report — say so explicitly for each."
)


def visible(texte: str) -> str:
    return _RAISONNEMENT.sub("", texte).strip()


def pause_sans_bilan(texte: str) -> bool:
    return len(visible(texte)) < BILAN_PROJET_MIN_CARACTERES


def reste_faisable(texte: str) -> bool:
    """Le bilan rend-il à l'utilisateur une action que le modèle pouvait jouer lui-même ?"""
    texte_visible = visible(texte)
    section = _SECTION_RESTE.search(texte_visible)
    return section is not None and _ACTION_FAISABLE.search(texte_visible, section.end()) is not None


__all__ = [
    "BILAN_PROJET_MIN_CARACTERES",
    "CONSIGNE_RESTE_FAISABLE",
    "CONSIGNE_SUITE_PROJET",
    "RELANCES_RESTE_MAX",
    "pause_sans_bilan",
    "reste_faisable",
]
