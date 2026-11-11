"""La relecture du prompt se voit : `prompt_progress` de llama-server devient la phase `lecture` (2026-11-11)."""

from __future__ import annotations

import asyncio
import json

from backend.inference.activite import SuiviActivite, progression
from backend.inference.engines_adapters.adaptateur_llama_server import _decoder_evenement
from backend.inference.engines_adapters.processus_llama_server import ARGUMENTS_POINTS_DE_REPRISE


def test_prompt_progress_est_decode() -> None:
    ligne = "data: " + json.dumps({"choices": [{"delta": {}}],
                                   "prompt_progress": {"total": 20000, "cache": 8000, "processed": 14000}})
    delta = _decoder_evenement(ligne)
    assert delta is not None and delta.lecture == {"total": 20000, "cache": 8000, "processed": 14000}


def test_la_phase_lecture_compte_hors_cache() -> None:
    suivi = SuiviActivite()
    asyncio.run(progression(suivi, {"lecture": {"total": 20000, "cache": 8000, "processed": 14000}}, None))
    etat = suivi.instantane(force=True) or {}
    assert etat["phase"] == "lecture" and etat["lecture"] == {"faits": 6000, "total": 12000}
    assert suivi.jetons == 0
    suivi.texte("Je ")
    assert (suivi.instantane(force=True) or {})["lecture"] is None


def test_un_point_de_reprise_par_tour() -> None:
    assert ARGUMENTS_POINTS_DE_REPRISE[:2] == ("--checkpoint-min-step", "256")
