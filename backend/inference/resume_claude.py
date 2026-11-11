"""Résumé de compaction confié à Claude Haiku 5.5, par le compte Claude Code de l'hôte.

Demande de Chris (2026-11-10) : avec le 35B-A3B local, un /compact relisait ~58K tokens et prenait 7 à 8 min,
page muette. Le conteneur n'a pas le compte Claude Code : il poste le matériau au relais de l'hôte
(`docker/resumeur-hote/serveur.py`, `claude -p`). Ce module rend `None` dès que le relais ne répond pas
(non configuré, éteint, refus, hors ligne), et l'appelant retombe sur le modèle local.
"""

from __future__ import annotations

import os

import httpx
from loguru import logger

DELAI_S = 320.0


def _url() -> str:
    return os.environ.get("RESUMEUR_URL", "").strip()


async def resumer(systeme: str, corps: str) -> str | None:
    """Résumé rédigé par Haiku sur l'hôte, ou `None` si le relais n'a pas pu le produire."""
    url, jeton = _url(), os.environ.get("RESUMEUR_JETON", "").strip()
    if not url or not jeton:
        return None
    try:
        async with httpx.AsyncClient(timeout=DELAI_S) as client:
            reponse = await client.post(f"{url}/resumer", json={"systeme": systeme, "corps": corps},
                                        headers={"Authorization": f"Bearer {jeton}"})
    except httpx.HTTPError as exc:
        logger.warning("Relais de résumé injoignable ({}) : repli sur le modèle local.", exc)
        return None
    if reponse.status_code != 200:
        logger.warning("Relais de résumé en échec ({}) : {} — repli local.", reponse.status_code, reponse.text[:300])
        return None
    texte = str(reponse.json().get("texte", "")).strip()
    if texte:
        logger.info("Résumé de compaction rédigé par Claude Haiku ({} caractères).", len(texte))
    return texte or None


__all__ = ["resumer"]
