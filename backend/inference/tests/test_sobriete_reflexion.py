"""Réflexion raccourcie sans être coupée : budget par tour, NoWait, champs propres à chaque moteur."""

from __future__ import annotations

import asyncio

from backend.inference import budget_reflexion
from backend.inference.engines_adapters import processus_vllm, sobriete_reflexion
from backend.inference.engines_adapters.contrat import OptionsGeneration


def test_le_budget_suit_l_issue_du_tour_precedent() -> None:
    base = OptionsGeneration()
    assert budget_reflexion.options_du_tour(base, "debut").budget_reflexion == budget_reflexion.BUDGET_PREMIER_TOUR
    assert budget_reflexion.options_du_tour(base, "succes").budget_reflexion == budget_reflexion.BUDGET_APRES_SUCCES
    assert budget_reflexion.options_du_tour(base, "echec").budget_reflexion == budget_reflexion.BUDGET_APRES_ECHEC
    assert budget_reflexion.options_du_tour(base, "relance").budget_reflexion == budget_reflexion.BUDGET_RELANCE
    assert budget_reflexion.options_du_tour(base, "succes").bannir_hesitations
    assert base.budget_reflexion is None, "les options d'origine ne sont pas modifiées"


def test_seuls_les_mots_d_un_seul_token_sont_bannis() -> None:
    async def jetons(mot: str) -> list[int]:
        return [7] if mot == "Wait" else ([8, 9] if mot == " Alternatively" else [100 + len(mot)])

    biais = asyncio.run(sobriete_reflexion.biais_hesitation(jetons))
    assert biais["7"] == sobriete_reflexion.BIAIS_HESITATION
    assert "8" not in biais and "9" not in biais


def test_un_mot_non_tokenisable_ne_bloque_rien() -> None:
    async def jetons(mot: str) -> list[int]:
        raise RuntimeError("tokenize indisponible")

    assert asyncio.run(sobriete_reflexion.biais_hesitation(jetons)) == {}


def test_les_champs_de_chaque_moteur() -> None:
    assert sobriete_reflexion.champs_llama_server(512, {"7": -100.0}) == {
        "thinking_budget_tokens": 512,
        "reasoning_budget_message": sobriete_reflexion.MESSAGE_FIN_REFLEXION,
        "logit_bias": {"7": -100.0},
    }
    assert sobriete_reflexion.champs_vllm(512, None) == {"thinking_token_budget": 512}
    assert sobriete_reflexion.champs_vllm(None, None) == {}


def test_vllm_est_lance_avec_la_config_de_raisonnement() -> None:
    assert '"reasoning_parser": "qwen3"' in processus_vllm.CONFIG_REFLEXION_VLLM
    assert "</think>" in processus_vllm.CONFIG_REFLEXION_VLLM
