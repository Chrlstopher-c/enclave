"""Événements SSE de llama-server traduits en deltas : texte, fragments d'appels, avancement de la relecture.

Fonction PURE et sans état : `_Accumulateur` (dans l'adaptateur) recompose les appels. Séparé de l'adaptateur le
2026-11-11, quand `prompt_progress` s'y est ajouté et l'a fait passer au-dessus de 500 lignes.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

PREFIXE_SSE = "data: "
MARQUEUR_FIN_SSE = "[DONE]"


class _Delta(BaseModel):
    """Ce qu'un événement SSE apporte : du texte, et/ou des FRAGMENTS d'appels d'outils."""

    contenu: str = ""
    fragments: list[dict[str, Any]] = Field(default_factory=list)
    raison_arret: str | None = None
    fin: bool = False
    # Relecture du prompt en cours : {"total", "cache", "processed", "time_ms"} tels que llama-server les envoie.
    lecture: dict[str, int] | None = None


def _decoder_evenement(ligne: str) -> _Delta | None:
    """Traduit une ligne SSE en delta. `None` pour tout ce qui n'est pas un événement.

    Fonction PURE et sans état : elle ne sait pas ce qui a précédé, donc elle ne peut pas
    reconstituer un appel d'outil. C'est `_Accumulateur` qui le fait — la séparation est
    délibérée, et c'est exactement ce qui manquait dans la version qui a produit le défaut décrit
    sur `_Accumulateur`.
    """
    if not ligne or not ligne.startswith(PREFIXE_SSE):
        return None
    charge = ligne[len(PREFIXE_SSE):].strip()
    if charge == MARQUEUR_FIN_SSE:
        return _Delta(fin=True)
    try:
        evenement = json.loads(charge)
    except json.JSONDecodeError:
        logger.warning("Événement SSE llama-server illisible, ignoré : {}", charge[:120])
        return None
    choix = (evenement.get("choices") or [{}])[0]
    delta = choix.get("delta") or {}
    # `reasoning_content` est délibérément IGNORÉ : le serveur tourne avec `--reasoning-format
    # none`, qui laisse les balises de réflexion dans `content`. Le lire en plus dupliquerait la
    # réflexion — une fois balisée dans le contenu, une fois nue à côté.
    return _Delta(
        contenu=delta.get("content") or "",
        fragments=list(delta.get("tool_calls") or []),
        raison_arret=choix.get("finish_reason"),
        lecture=_lecture(evenement.get("prompt_progress")),
    )


def _lecture(brut: Any) -> dict[str, int] | None:
    if not isinstance(brut, dict):
        return None
    return {cle: int(brut[cle]) for cle in ("total", "cache", "processed") if isinstance(brut.get(cle), (int, float))}
