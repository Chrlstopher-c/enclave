"""Outil `recuperer_page` — lire le contenu d'une page web dont on a déjà l'adresse.

Compagnon de `recherche_web`, et la moitié qui lui manquait : la recherche rend des titres, des
adresses et des extraits de deux lignes. Un extrait suffit pour choisir une source, jamais pour
répondre — et un modèle qui n'a que l'extrait comble le reste de mémoire, ce que le socle interdit
précisément (« never present your own knowledge as a search result »). Sans cet outil, le harnais
crée l'écart qu'il reproche ensuite au modèle.

Le second usage est plus direct encore : une adresse donnée par l'utilisateur. Aucune recherche
n'est nécessaire, il faut lire la page — documentation, page de version, fil de discussion.

EXTRACTION SANS DÉPENDANCE : `bs4`, `lxml`, `html2text` et `readability` sont absents de l'image —
vérifié plutôt que supposé. L'extraction est donc écrite ici, en trois gestes qui couvrent
l'essentiel du HTML réel : retirer les blocs qui ne portent pas de texte lisible (script, style,
navigation), retirer les balises restantes, décoder les entités. Ce n'est pas un analyseur HTML et
cela ne prétend pas l'être : c'est un extracteur de texte, et son défaut connu est de laisser
passer du texte de menu sur les pages très structurées.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

import httpx
from loguru import logger

from backend.outils.contrat import ContexteExecution, DescriptionOutil, EchecOutil, Outil
from backend.outils.diagnostic_web import echec_http, echec_reseau

NOM = "recuperer_page"

# Le texte extrait repart dans le contexte du modèle. `ResultatOutil.tronque()` borne déjà en aval ;
# cette borne-ci est plus basse à dessein : une page entière chasserait l'historique de la
# conversation, et l'essentiel d'une page de documentation tient largement dedans.
LONGUEUR_PAGE_MAX = 6_000

# Un serveur lent ne doit pas immobiliser le tour. Plus généreux que la recherche — SearXNG est
# local, une page arbitraire ne l'est pas.
DELAI_S = 20.0

# Taille lue au maximum, avant extraction : garde-fou contre une réponse énorme (archive, média
# servi en text/html). Le corps est tronqué, pas la connexion : on lit ce qui est utile et on ferme.
OCTETS_MAX = 3_000_000

# Un agent HTTP absent ou trop nu fait répondre 403 à beaucoup de sites. Celui-ci dit ce qu'il est.
AGENT = "Mozilla/5.0 (X11; Linux x86_64) EchoHub/2.0 (+outil recuperer_page)"

# Blocs dont le contenu n'est jamais du texte de lecture. Retirés AVEC leur contenu, contrairement
# aux autres balises dont seul le marquage part — sans quoi le corps d'un script se retrouverait
# dans le texte rendu au modèle.
_BLOCS_MUETS = re.compile(
    r"<(script|style|noscript|svg|canvas|nav|header|footer|form|aside|template)\b.*?</\1\s*>",
    re.DOTALL | re.IGNORECASE)
_COMMENTAIRES = re.compile(r"<!--.*?-->", re.DOTALL)
# Balises de rupture, converties en saut de ligne avant de retirer le reste : sans cela, un article
# entier arrive au modèle en un seul paragraphe illisible.
_RUPTURES = re.compile(r"</?(p|div|br|li|tr|h[1-6]|section|article|blockquote)\b[^>]*>", re.IGNORECASE)
_BALISES = re.compile(r"<[^>]+>")
_LIGNES_VIDES = re.compile(r"\n\s*\n\s*\n+")
_ESPACES = re.compile(r"[ \t ]+")
# JSON et texte brut (API PyPI, README bruts de GitHub) : rendus tels quels, l'extraction HTML les abîmerait.
_BRUT = re.compile(r"json|text/plain|text/markdown|text/x-")
_TITRE = re.compile(r"<title\b[^>]*>(.*?)</title\s*>", re.DOTALL | re.IGNORECASE)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": (
                "Full address of the page to read, starting with http:// or https:// — for "
                "example `https://docs.python.org/3/library/asyncio.html`. Required: a call "
                "without it does nothing."
            ),
        },
    },
    "required": ["url"],
}

DESCRIPTION = DescriptionOutil(
    nom=NOM,
    description=(
        "Really fetches a web page and returns its readable text. Use it when a search result "
        "matters and its two-line snippet is not enough, or when the user gives you an address to "
        "read. Returns the page title and its text, truncated if long; JSON and plain text come back raw "
        "(e.g. `https://pypi.org/pypi/<package>/json` gives a package's real documentation URLs). It cannot "
        "log in, fill a form, or run the page's scripts. On failure it tells you WHY (missing page, site "
        "down, no Internet…) and whether retrying can help: follow that, never retry a permanent failure."
    ),
    parametres=_SCHEMA,
    alias={a: "url" for a in ("adresse", "lien", "link", "page", "uri", "address", "chemin")},
)


def _texte_lisible(brut: str) -> str:
    """Texte d'une page HTML, dans l'ordre où les gestes doivent s'enchaîner.

    L'ordre n'est pas indifférent : retirer les balises AVANT les blocs muets laisserait le corps
    des scripts dans le texte. Les ruptures deviennent des sauts de ligne AVANT le retrait général,
    faute de quoi la structure du document disparaît entièrement.
    """
    sans_muets = _BLOCS_MUETS.sub(" ", _COMMENTAIRES.sub(" ", brut))
    aere = _RUPTURES.sub("\n", sans_muets)
    nu = html.unescape(_BALISES.sub(" ", aere))
    lignes = [_ESPACES.sub(" ", ligne).strip() for ligne in nu.split("\n")]
    return _LIGNES_VIDES.sub("\n\n", "\n".join(ligne for ligne in lignes if ligne)).strip()


def _titre(brut: str) -> str:
    trouve = _TITRE.search(brut)
    if not trouve:
        return ""
    return _ESPACES.sub(" ", html.unescape(_BALISES.sub("", trouve.group(1)))).strip()


def _valider(url: str) -> str:
    """Adresse utilisable, ou refus expliqué au modèle avec la forme attendue."""
    propre = url.strip().strip("<>\"'")
    if not propre:
        raise EchecOutil(
            "No address given. Send the `url` argument with the full address, "
            'for example: {"url": "https://example.com/page"}')
    if not propre.startswith(("http://", "https://")):
        raise EchecOutil(
            f"« {propre} » is not a web address. It must start with http:// or https://. "
            "To read a file of this conversation, use `lire_fichier` instead.")
    return propre


async def executer(arguments: dict[str, Any], _: ContexteExecution) -> str:
    """Récupère la page et rend son texte. Un échec réseau est un résultat, pas une panne.

    Le contenu récupéré est une entrée non fiable et repart dans le contexte du modèle : il est
    donc borné en taille à la lecture ET après extraction. Le type de contenu est vérifié — servir
    une archive de 200 Mo sous `text/html` est un cas réel, pas une hypothèse.
    """
    url = _valider(str(arguments.get("url", "")))
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=DELAI_S,
                                     headers={"User-Agent": AGENT}) as client:
            reponse = await client.get(url)
            reponse.raise_for_status()
            brut = reponse.text[:OCTETS_MAX]
            genre = reponse.headers.get("content-type", "").lower()
    except httpx.HTTPStatusError as exc:
        logger.warning("recuperer_page : {} a répondu {}", url, exc.response.status_code)
        raise EchecOutil(echec_http(url, exc.response.status_code)) from exc
    except httpx.HTTPError as exc:
        logger.warning("recuperer_page : {} injoignable : {!r}", url, exc)
        raise EchecOutil(await echec_reseau(url, exc)) from exc
    return _rendre(url, genre, brut)


def _rendre(url: str, genre: str, brut: str) -> str:
    """Texte rendu au modèle selon le type de contenu : brut (JSON, texte), refus expliqué, ou page lisible."""
    if _BRUT.search(genre):
        return _borne(f"Page : {url} ({genre.split(';')[0]}, raw)", _fiche_pypi(brut) or brut.strip())
    if genre and "html" not in genre and not genre.startswith("text/"):
        raise EchecOutil(
            f"FETCH UNUSABLE — {url} is a {genre.split(';')[0]} file, not a web page: this tool reads text only. "
            "Download it with `executer_commande` (curl -sLo file URL) and inspect it there if you need it.")
    texte = _texte_lisible(brut)
    if not texte:
        raise EchecOutil(
            f"FETCH EMPTY — {url} answered, but has no readable text: the page is built by JavaScript in the browser "
            "(this tool does not run scripts). PERMANENT for this tool. Use the `playwright` browser (MCP) to read it, "
            "or another source.")
    titre = _titre(brut)
    logger.info("recuperer_page : {} — {} caractères extraits", url, len(texte))
    return _borne(f"Page : {url}" + (f"\nTitre : {titre}" if titre else ""), texte)


def _fiche_pypi(brut: str) -> str | None:
    """JSON de l'API PyPI réduit à ce qui sert : version, résumé et VRAIES adresses de documentation.

    Brut, le README d'une page PyPI occupe les 6 000 caractères et coupe les liens (`project_urls`) qui sont la raison
    même de l'appel.
    """
    try:
        info = json.loads(brut).get("info")
    except (ValueError, AttributeError):
        return None
    if not isinstance(info, dict) or "project_urls" not in info:
        return None
    liens = {**({"Homepage": info["home_page"]} if info.get("home_page") else {}), **(info.get("project_urls") or {})}
    lignes = [f"Package: {info.get('name')} {info.get('version')} — {info.get('summary') or ''}",
              f"Requires Python: {info.get('requires_python') or '?'}", "Official links (use these, never guess):"]
    lignes += [f"- {nom}: {adresse}" for nom, adresse in liens.items()]
    return "\n".join(lignes)


def _borne(entete: str, texte: str) -> str:
    if len(texte) > LONGUEUR_PAGE_MAX:
        texte = (f"{texte[:LONGUEUR_PAGE_MAX]}\n\n[page truncated at {LONGUEUR_PAGE_MAX} characters; the rest "
                 "is not available through this tool]")
    return f"{entete}\n\n{texte}"

OUTIL = Outil(description=DESCRIPTION, executer=executer)

__all__ = ["OUTIL"]
