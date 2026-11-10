"""Forme des messages exigée par les gabarits : un seul `system`, et en tête.

Constaté le 2026-11-10 (Ornith 1.5 sous vLLM, gabarit Qwen 3.5) : après une compaction, le résumé était
inséré comme SECOND message `system` ; le gabarit l'a refusé (« System message must be at the
beginning ») et la tâche s'est arrêtée net. Les deux compactions (`chat.compaction`, `compaction_boucle`)
en produisent ; plutôt que de compter sur chaque producteur, la forme est garantie ici, juste avant le
moteur : les `system` de tête sont fusionnés en un seul, un `system` plus loin devient un message `user`.
"""

from __future__ import annotations

from collections.abc import Sequence

from backend.inference.engines_adapters.contrat import MessageChat


def un_seul_systeme(messages: Sequence[MessageChat]) -> list[MessageChat]:
    """Messages prêts pour n'importe quel gabarit : au plus un `system`, en première position."""
    tete: list[str] = []
    rang = 0
    while rang < len(messages) and messages[rang].role == "system" and isinstance(messages[rang].content, str):
        tete.append(str(messages[rang].content))
        rang += 1
    sortie: list[MessageChat] = []
    if tete:
        sortie.append(messages[0] if len(tete) == 1 else MessageChat(role="system", content="\n\n".join(tete)))
    for message in messages[rang:]:
        sortie.append(message.model_copy(update={"role": "user"}) if message.role == "system" else message)
    return sortie


__all__ = ["un_seul_systeme"]
