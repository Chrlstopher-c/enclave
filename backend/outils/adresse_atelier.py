"""Adresse de l'atelier vue d'un serveur MCP — `localhost` y désigne un AUTRE conteneur.

Le navigateur `playwright` tourne dans son propre conteneur : `http://localhost:8123` y est refusé, alors
que le même `curl` passe depuis le shell de l'atelier. Constaté le 2026-11-11 (« Tetris test 35B ») : le
modèle a perdu plusieurs tours à le comprendre, puis a deviné l'IP interne du conteneur. Les URL locales
passées à un outil MCP sont donc réécrites vers le nom de l'atelier, et le modèle en est prévenu.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from backend.core.config import get_settings

_LOCAL = re.compile(r"(https?://)(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?=[:/'\"\s]|$)")


def hote_atelier() -> str:
    """Nom d'hôte de l'atelier sur le réseau des conteneurs (tiré de `ATELIER_URL`)."""
    return urlparse(get_settings().atelier_url).hostname or "localhost"


def vers_atelier(parametres: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Les paramètres avec leurs URL locales réécrites, et une note pour le modèle si quelque chose a changé."""
    hote = hote_atelier()
    if hote in ("localhost", "127.0.0.1"):
        return parametres, None
    remplace = rf"\g<1>{hote}"
    sortie: dict[str, Any] = {}
    change = False
    for cle, valeur in parametres.items():
        if isinstance(valeur, str) and _LOCAL.search(valeur):
            sortie[cle] = _LOCAL.sub(remplace, valeur)
            change = True
        else:
            sortie[cle] = valeur
    if not change:
        return parametres, None
    note = (f"(Adresse locale réécrite en http://{hote}:<port> : le navigateur tourne dans un autre conteneur, "
            f"où localhost ne mène pas à l'atelier. Utilise directement http://{hote}:<port>.)")
    return sortie, note
