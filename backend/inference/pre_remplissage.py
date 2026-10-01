"""Pré-remplir l'ouverture d'un appel d'outil après une annonce non tenue.

Mesuré le 2026-10-02 (Chris) : « je vais lire le fichier », 5-8 s de pause, la même phrase en anglais,
une réflexion, puis enfin la lecture. Chaque relance par consigne fait REPENSER le modèle, qui
reformule son annonce au lieu d'agir. Ici le tour d'assistant est rouvert sur son annonce suivie de
`<tool_call>` : il ne lui reste qu'à écrire les arguments. Vérifié sur llama-server le même jour —
l'appel revient structuré (`tool_calls`), sans réflexion, en une seconde.

llama-server renvoie en tête de flux ce qui était pré-rempli (précédé d'une réflexion vide) :
`sans_echo` le retire, sinon l'annonce s'afficherait deux fois.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from backend.inference.engines_adapters.contrat import MessageChat
from backend.inference.fin_projet import visible
from backend.inference.harnais_outils import _sans_appels_outils

OUVERTURE_APPEL = "<tool_call>\n"
_REFLEXION_VIDE = re.compile(r"^\s*<think>\s*</think>\s*")
_GABARIT_REFLEXION_VIDE = "<think>\n\n</think>\n\n"


def annonce(texte: str) -> str:
    return visible(_sans_appels_outils(texte)).strip()


def pre_remplir(messages: list[MessageChat], texte: str) -> list[MessageChat]:
    """Conversation dont le dernier tour d'assistant est l'annonce, laissée ouverte sur un appel."""
    contenu = f"{annonce(texte)}\n{OUVERTURE_APPEL}".lstrip()
    return list(messages) + [MessageChat(role="assistant", content=contenu)]


def _encore_echo(tampon: str, attendu: str) -> bool:
    """Le début de flux peut-il encore n'être que l'écho du pré-remplissage ?"""
    if "</think>" not in tampon:
        return _GABARIT_REFLEXION_VIDE.startswith(tampon.lstrip()) or attendu.startswith(tampon.lstrip())
    nu = _REFLEXION_VIDE.sub("", tampon)
    return len(nu) < len(attendu) and attendu.startswith(nu)


def _reste(tampon: str, attendu: str) -> str:
    nu = _REFLEXION_VIDE.sub("", tampon)
    return nu[len(attendu):].lstrip("\n") if attendu and nu.startswith(attendu) else nu


async def sans_echo(flux: AsyncIterator[dict[str, Any]], texte: str) -> AsyncIterator[dict[str, Any]]:
    """Le flux, privé de l'écho de l'annonce pré-remplie ; tout le reste passe tel quel."""
    attendu = annonce(texte)
    tampon = ""
    libre = False
    async for morceau in flux:
        fragment = morceau.get("texte")
        if libre or not isinstance(fragment, str):
            yield morceau
            continue
        tampon += fragment
        if _encore_echo(tampon, attendu):
            continue
        libre = True
        if reste := _reste(tampon, attendu):
            yield {**morceau, "texte": reste}
    if not libre and (reste := _reste(tampon, attendu)):
        yield {"texte": reste}


__all__ = ["OUVERTURE_APPEL", "annonce", "pre_remplir", "sans_echo"]
