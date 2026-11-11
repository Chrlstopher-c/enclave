"""Indice du harnais quand un appel réseau en ligne de commande tombe sur une adresse inexistante.

Relevé sur « TestSetup » (11/11/2026) : six adresses d'API tapées de mémoire, chacune refusée
(« Not Found », « Invalid value »), avant de lire la documentation — qui donnait la bonne en un essai.
`curl` rend 0 même sur un 404 : sans cet indice, rien ne dit au modèle d'arrêter de deviner.
"""

from __future__ import annotations

import re

_APPEL_RESEAU = re.compile(r"\b(?:curl|wget|http)\b[^|;&]*https?://", re.IGNORECASE)
_ADRESSE_REFUSEE = re.compile(
    r"\b404\b|not found|\bgone\b|invalid value|cannot (?:get|post)|no route|unknown endpoint"
    r"|[\"']error[\"']\s*[:,]\s*(?:true|[\"']reason)",
    re.IGNORECASE,
)

INDICE = (
    "HARNESS: the server rejected this URL (not found / invalid). Do NOT try another guessed URL or "
    "parameter: find the API documentation first (`recherche_web`, then `recuperer_page` on the doc) "
    "and call exactly the endpoint and parameter names it gives."
)


def indice(commande: str, sortie: str) -> str | None:
    """L'indice à joindre au compte rendu, ou `None` si la commande n'a pas buté sur une adresse."""
    if _APPEL_RESEAU.search(commande) and _ADRESSE_REFUSEE.search(sortie):
        return INDICE
    return None
