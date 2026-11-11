"""Diagnostic d'un échec web, dit au modèle comme son propre corps le sentirait : quoi, pourquoi, et quoi faire.

Origine (Chris, 2026-11-11) : « la page a échoué » sans cause laissait le modèle réessayer la même adresse
(refusée ensuite par le harnais), deviner des variantes d'URL, ou au contraire renoncer à toute la doc en ligne
et bricoler. Chaque message dit donc : la cause exacte, si elle est DÉFINITIVE ou PASSAGÈRE, que l'échec ne vaut
que pour CETTE adresse, et le prochain geste utile.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

import httpx
from loguru import logger

# Hôtes de référence pour savoir si c'est le site ou toute la connexion qui est en cause.
_REFERENCES = ("pypi.org", "github.com", "wikipedia.org")
_SEUL_CE_LIEN = "This concerns only this address: other pages and other sites are not affected."
_SOURCES = ("Take a URL from a `recherche_web` result (never guess one). For a Python/JS package, its "
            "installed code is the best documentation: `doc <package>` in the shell.")

_HTTP = {
    404: ("does not exist (HTTP 404). The site answered, but nothing is at this path: the URL is wrong or "
          "outdated. PERMANENT: retrying, or trying spelling variants of the path, will fail the same way."),
    410: "was removed for good (HTTP 410). PERMANENT.",
    401: "requires a login (HTTP 401). PERMANENT for you: you cannot log in.",
    403: ("refuses automated readers (HTTP 403). PERMANENT for this tool: retrying will not change it. "
          "The same content is often on another site (mirror, docs on GitHub, PyPI page)."),
    429: "rate-limited this tool (HTTP 429, too many requests). Do not retry this site now; use another source.",
}


def echec_http(url: str, statut: int) -> str:
    if statut in _HTTP:
        cause = _HTTP[statut]
    elif 500 <= statut < 600:
        cause = (f"failed on the server side (HTTP {statut}). TEMPORARY, on their side: one retry later may "
                 "work, but prefer another source now.")
    else:
        cause = f"answered HTTP {statut}, which is not a page. Treat it as unusable."
    return f"FETCH FAILED — {url} {cause}\n{_SEUL_CE_LIEN}\nNext: {_SOURCES}"


async def _internet_repond() -> bool:
    """Au moins un hôte de référence se résout : la connexion de la machine fonctionne."""
    boucle = asyncio.get_running_loop()
    for hote in _REFERENCES:
        try:
            await asyncio.wait_for(boucle.getaddrinfo(hote, 443), timeout=3)
            return True
        except (OSError, asyncio.TimeoutError):
            continue
    return False


async def echec_reseau(url: str, exc: httpx.HTTPError) -> str:
    hote = urlsplit(url).hostname or url
    internet = await _internet_repond()
    if not internet:
        logger.warning("diagnostic web : aucune référence joignable, connexion de la machine coupée")
        return (f"FETCH FAILED — {url}: the machine has NO Internet connection right now (even {_REFERENCES[0]} "
                "cannot be resolved). This is not about this site. Do not try other web calls now: work with "
                "local sources (`doc <package>`, `--help`, the installed code) and tell the user the web is down.")
    if isinstance(exc, httpx.ConnectError) and _nom_inconnu(exc):
        cause = (f"the domain « {hote} » does not exist (DNS: no such name), while the Internet works. "
                 "PERMANENT: the address is probably invented or misspelled. Do not try variants of it.")
    elif isinstance(exc, httpx.TimeoutException):
        cause = (f"« {hote} » did not answer in time, while the Internet works. TEMPORARY, on their side: at most "
                 "one retry later; prefer another source now.")
    elif isinstance(exc, httpx.ConnectError):
        cause = (f"« {hote} » refused or dropped the connection, while the Internet works. The site is down or "
                 "blocks this tool. Use another source.")
    elif "certificate" in str(exc).lower() or "ssl" in str(exc).lower():
        cause = f"« {hote} » has a broken HTTPS certificate. Unusable; use another source."
    else:
        cause = f"« {hote} » could not be read ({type(exc).__name__}: {exc}), while the Internet works."
    return f"FETCH FAILED — {url}: {cause}\n{_SEUL_CE_LIEN}\nNext: {_SOURCES}"


def _nom_inconnu(exc: Exception) -> bool:
    texte = f"{exc} {exc.__cause__ or ''}".lower()
    return any(m in texte for m in ("name or service not known", "nodename nor servname", "no address associated",
                                    "name does not resolve", "temporary failure in name resolution",
                                    "getaddrinfo failed"))

