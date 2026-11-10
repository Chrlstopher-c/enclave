"""Le dernier plan qui a RÉELLEMENT chargé chaque modèle — pour le recharger à l'identique d'un clic.

Demandé par Chris le 2026-11-10 : Ornith 1.5 refusait de se charger depuis le panneau, alors que le même
modèle chargé « à la main » (contexte, fraction de VRAM, graphes forcés) tenait. Un plan qui a abouti est
une mesure, pas une estimation : on le garde sur disque, par modèle, et le panneau propose de le rejouer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from backend.core.config import get_settings
from backend.inference.engines_adapters.contrat import PlanChargement

NOM_FICHIER = "plans_eprouves.json"


def _fichier() -> Path:
    return get_settings().data_dir / NOM_FICHIER


def _tous() -> dict[str, Any]:
    try:
        contenu = json.loads(_fichier().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("Plans éprouvés illisibles ({}) : ignorés.", exc)
        return {}
    return contenu if isinstance(contenu, dict) else {}


def retenir(plan: PlanChargement) -> None:
    """Enregistre le plan d'un chargement réussi ; ne casse jamais le chargement s'il échoue."""
    plans = _tous()
    plans[plan.nom_affiche] = plan.model_dump(mode="json")
    try:
        _fichier().write_text(json.dumps(plans, indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        logger.warning("Plan éprouvé non enregistré pour {} : {}", plan.nom_affiche, exc)


def lire(identifiant: str) -> PlanChargement | None:
    """Plan éprouvé du modèle, ou `None` s'il n'a jamais été chargé avec succès."""
    brut = _tous().get(identifiant)
    if brut is None:
        return None
    try:
        return PlanChargement.model_validate(brut)
    except ValueError as exc:
        logger.warning("Plan éprouvé de {} invalide : {}", identifiant, exc)
        return None


__all__ = ["lire", "retenir"]
