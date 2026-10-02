"""Domaine `retours` — verdicts portés sur les réponses du modèle (👍, 👎, correction).

Ils alimentent le réentraînement d'un modèle local : un 👍 ou un 👎 isolé sert à la méthode KTO,
deux variantes du même tour notées différemment forment une paire DPO, une correction devient un
exemple SFT. Le domaine relit la conversation via l'interface publique de `chat` et garde chaque
exemple autonome ; l'export JSONL (`GET /retours/export.jsonl`) est son unique sortie.
"""

from backend.retours.routes import PREFIXE, routeur

__all__ = ["routeur", "PREFIXE"]
