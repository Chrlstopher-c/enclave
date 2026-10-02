"""Serveurs MCP déclarés dans `~agent/mcp.json`, et les deux outils qui les exposent au modèle.

Comme les outils « différés » de Claude Code : déclarer les ~20 outils de Playwright (schémas compris)
coûterait des milliers de tokens à CHAQUE tour. Le modèle n'a donc que deux outils fixes —
`mcp_outils` (découvrir ce qu'un serveur offre, schémas compris) et `mcp_appeler` (l'utiliser) — et
le coût du prompt ne dépend pas du nombre de serveurs. AWARENESS.md en donne la liste.

Format de `mcp.json` (celui de Claude Code est accepté tel quel) :
    {"mcpServers": {"playwright": {"url": "http://echohub-navigateur:8931/mcp"},
                    "autre": {"command": "npx", "args": ["-y", "pkg"], "env": {}}}}
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

from backend.agent import MCP, racine
from backend.outils.contrat import ContexteExecution, DescriptionOutil, EchecOutil, Outil
from backend.outils.mcp_client import ClientMCP, ErreurMCP, TransportHTTP, TransportStdio

SORTIE_MAX = 12_000
# Client par serveur, avec la signature de sa définition et la boucle asyncio qui l'a créé : un client
# (verrou, pipes, session httpx) ne sert jamais dans une autre boucle que la sienne.
_CLIENTS: dict[str, ClientMCP] = {}
_SIGNATURE: dict[str, tuple[str, int]] = {}
# Noms d'outils déjà découverts, par serveur : AWARENESS les cite sans rappeler le réseau à chaque prompt.
_CONNUS: dict[str, list[str]] = {}


def configuration() -> dict[str, dict[str, Any]]:
    """Serveurs déclarés, nom → définition. Fichier absent ou illisible : aucun serveur."""
    chemin = racine() / MCP
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("~agent/{} illisible : {}", MCP, exc)
        return {}
    serveurs = brut.get("mcpServers", brut.get("serveurs", {})) if isinstance(brut, dict) else {}
    return {nom: d for nom, d in serveurs.items() if isinstance(d, dict) and not d.get("disabled")}


def _client(nom: str) -> ClientMCP:
    definition = configuration().get(nom)
    if definition is None:
        connus = ", ".join(configuration()) or "aucun"
        raise EchecOutil(f"Serveur MCP inconnu : « {nom} ». Serveurs déclarés : {connus}.")
    signature = (json.dumps(definition, sort_keys=True), id(asyncio.get_running_loop()))
    if nom not in _CLIENTS or _SIGNATURE.get(nom) != signature:
        if definition.get("url"):
            transport: Any = TransportHTTP(str(definition["url"]), definition.get("headers"))
        elif definition.get("command"):
            transport = TransportStdio([str(definition["command"]), *map(str, definition.get("args", []))],
                                       definition.get("env"))
        else:
            raise EchecOutil(f"Serveur MCP « {nom} » sans `url` ni `command` dans ~agent/{MCP}.")
        _CLIENTS[nom], _SIGNATURE[nom] = ClientMCP(nom, transport), signature
    return _CLIENTS[nom]


def _decrire(outil: dict[str, Any], detail: bool) -> str:
    resume = (str(outil.get("description") or "").strip().splitlines() or [""])[0]
    ligne = f"- {outil['name']}: {resume}"
    if not detail:
        return ligne
    return f"{ligne}\n  arguments: {json.dumps(outil.get('inputSchema', {}), ensure_ascii=False)}"


def serveurs_connus() -> list[tuple[str, list[str]]]:
    """(serveur, lignes à afficher) sans appel réseau : description déclarée + outils déjà découverts."""
    lignes: list[tuple[str, list[str]]] = []
    for nom, definition in configuration().items():
        details = [str(definition["description"])] if definition.get("description") else []
        outils = _CONNUS.get(nom)
        details.append(f"outils : {', '.join(outils)}" if outils else "outils : `mcp_outils` avec ce serveur")
        lignes.append((nom, details))
    return lignes


async def noms_outils() -> list[tuple[str, list[str]]]:
    """(serveur, noms de ses outils) pour AWARENESS ; un serveur injoignable est signalé, pas fatal."""
    resultat: list[tuple[str, list[str]]] = []
    for nom in configuration():
        try:
            resultat.append((nom, [o["name"] for o in await _client(nom).outils()]))
        except (ErreurMCP, EchecOutil) as exc:
            resultat.append((nom, [f"(injoignable : {exc})"]))
    return resultat


DESCRIPTION_OUTILS = DescriptionOutil(
    nom="mcp_outils",
    description=(
        "Lists what an MCP server offers (the servers are listed in `~agent/AWARENESS.md`, section "
        "« Serveurs MCP »). Without `outil`: every tool with one line each. With `outil`: that tool's "
        "full argument schema — fetch it before the first `mcp_appeler` of a tool."
    ),
    parametres={"type": "object", "properties": {
        "serveur": {"type": "string", "description": "Server name, e.g. `playwright`."},
        "outil": {"type": "string", "description": "Optional: one tool name, to get its argument schema."},
    }, "required": ["serveur"]},
    alias={"server": "serveur", "tool": "outil", "name": "outil"},
)

DESCRIPTION_APPELER = DescriptionOutil(
    nom="mcp_appeler",
    description=(
        "Calls a tool of an MCP server, e.g. the `playwright` browser for end-to-end tests: "
        "`browser_navigate`, then `browser_snapshot` (an accessibility tree in TEXT — you cannot see "
        "images), `browser_click` / `browser_type` with the `ref` the snapshot gives."
    ),
    parametres={"type": "object", "properties": {
        "serveur": {"type": "string", "description": "Server name."},
        "outil": {"type": "string", "description": "Tool name, as listed by `mcp_outils`."},
        "arguments": {"type": "object", "description": "The tool's arguments, as its schema describes them."},
    }, "required": ["serveur", "outil"]},
    alias={"server": "serveur", "tool": "outil", "name": "outil", "args": "arguments", "params": "arguments"},
)


async def _lister(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
    args = DESCRIPTION_OUTILS.normaliser(arguments)
    nom, voulu = str(args.get("serveur", "")).strip(), str(args.get("outil", "") or "").strip()
    try:
        outils = await _client(nom).outils()
    except ErreurMCP as exc:
        raise EchecOutil(f"Échec : serveur MCP « {nom} » : {exc}") from exc
    _CONNUS[nom] = [o["name"] for o in outils]
    if voulu:
        trouve = [o for o in outils if o["name"] == voulu]
        if not trouve:
            noms = ", ".join(o["name"] for o in outils)
            raise EchecOutil(f"« {voulu} » n'existe pas sur « {nom} ». Outils : {noms}.")
        return _decrire(trouve[0], detail=True)
    return f"{len(outils)} outil(s) sur « {nom} » :\n" + "\n".join(_decrire(o, detail=False) for o in outils)


async def _appeler(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
    args = DESCRIPTION_APPELER.normaliser(arguments)
    nom, outil = str(args.get("serveur", "")).strip(), str(args.get("outil", "")).strip()
    parametres = args.get("arguments") or {}
    if isinstance(parametres, str):
        try:
            parametres = json.loads(parametres)
        except json.JSONDecodeError as exc:
            raise EchecOutil(f"Échec : `arguments` n'est pas un objet JSON ({exc}).") from exc
    if not nom or not outil or not isinstance(parametres, dict):
        raise EchecOutil('Échec : `mcp_appeler` attend {"serveur": …, "outil": …, "arguments": {…}}.')
    try:
        texte, en_erreur = await _client(nom).appeler(outil, parametres)
    except ErreurMCP as exc:
        raise EchecOutil(f"Échec : {nom}.{outil} : {exc}") from exc
    if len(texte) > SORTIE_MAX:
        texte = f"{texte[:SORTIE_MAX]}\n[… sortie tronquée à {SORTIE_MAX} caractères sur {len(texte)}]"
    if en_erreur:
        raise EchecOutil(f"Échec : {nom}.{outil} : {texte}")
    return texte or "(aucune sortie)"


OUTIL_MCP_OUTILS = Outil(description=DESCRIPTION_OUTILS, executer=_lister)
OUTIL_MCP_APPELER = Outil(description=DESCRIPTION_APPELER, executer=_appeler)

__all__ = ["OUTIL_MCP_APPELER", "OUTIL_MCP_OUTILS", "configuration", "noms_outils", "serveurs_connus"]
