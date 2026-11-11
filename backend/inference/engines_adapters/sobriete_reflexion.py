"""Sobriété de la réflexion — la raccourcir sans la désactiver, pour les deux moteurs.

Mesuré le 2026-11-11 (« Tetris test », Ornith 35B) : ~10 000 tokens de réflexion sur 21 min, des blocs de
5 000 à 9 000 caractères après des appels RÉUSSIS, truffés de « Wait », « Actually », « Hmm ». Deux leviers :

- un BUDGET de tokens de réflexion par requête. Épuisé, le moteur insère un message de clôture et le
  modèle passe à l'action (llama-server : `thinking_budget_tokens` + `reasoning_budget_message` ;
  vLLM : `thinking_token_budget`, la clôture étant fixée au lancement par `--reasoning-config`) ;
- NoWait (arXiv 2506.08343) : un `logit_bias` qui interdit les tokens d'hésitation en tête de phrase.
  Chaînes 27 à 51 % plus courtes sur Qwen3, sans perte rapportée. Seules les formes CAPITALISÉES sont
  visées : elles ouvrent une remise en question, et n'apparaissent presque jamais dans du code.

`presence_penalty` n'est PAS un levier : à 1,5 le modèle bouclait sur du vocabulaire aléatoire (Chris).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from loguru import logger

MOTS_HESITATION = ("Wait", " Wait", "Hmm", " Hmm", "Actually", " Actually", "Alternatively", " Alternatively")
BIAIS_HESITATION = -100.0
MESSAGE_FIN_REFLEXION = "\n\nEnough thinking for this step: act now.\n"


async def biais_hesitation(tokeniser: Callable[[str], Awaitable[list[int]]]) -> dict[str, float]:
    """`logit_bias` des mots d'hésitation qui tiennent en UN token (un mot coupé toucherait des sous-mots communs)."""
    biais: dict[str, float] = {}
    for mot in MOTS_HESITATION:
        try:
            jetons = await tokeniser(mot)
        except Exception as exc:  # noqa: BLE001 — un mot non tokenisé ne doit jamais bloquer une génération
            logger.warning("NoWait : « {} » non tokenisé ({}).", mot, exc)
            continue
        if len(jetons) == 1:
            biais[str(jetons[0])] = BIAIS_HESITATION
    logger.info("NoWait : {} token(s) d'hésitation bannis.", len(biais))
    return biais


def champs_llama_server(budget: int | None, biais: dict[str, float] | None) -> dict[str, object]:
    """Champs à ajouter à une requête llama-server."""
    champs: dict[str, object] = {}
    if budget is not None:
        champs["thinking_budget_tokens"] = budget
        champs["reasoning_budget_message"] = MESSAGE_FIN_REFLEXION
    if biais:
        champs["logit_bias"] = biais
    return champs


def champs_vllm(budget: int | None, biais: dict[str, float] | None) -> dict[str, object]:
    """Champs à ajouter à une requête vLLM (le message de clôture est fixé au lancement du serveur)."""
    champs: dict[str, object] = {}
    if budget is not None:
        champs["thinking_token_budget"] = budget
    if biais:
        champs["logit_bias"] = biais
    return champs
