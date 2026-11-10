"""Un plan qui a abouti se rejoue à l'identique (Chris, 2026-11-10 : Ornith refusait de se charger)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.inference import plans_eprouves
from backend.inference.engines_adapters.contrat import MoteurSupporte, PlanChargement


def test_retenu_puis_relu(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(plans_eprouves, "_fichier", lambda: tmp_path / "plans.json")
    plan = PlanChargement(moteur=MoteurSupporte.VLLM, chemin_modele="/m", identifiant_modele="ornith",
                          couches_gpu=32, contexte=65536, batch=2048, type_kv_cache="q8_0", fraction_vram=0.77)
    assert plans_eprouves.lire("ornith") is None
    plans_eprouves.retenir(plan)
    relu = plans_eprouves.lire("ornith")
    assert relu is not None and relu.contexte == 65536 and relu.fraction_vram == 0.77
