"""Client MCP minimal — juste ce qu'il faut pour des OUTILS : initialize, tools/list, tools/call.

Deux transports, tels que la spec MCP les définit :
- HTTP « streamable » : POST JSON-RPC ; la réponse est du JSON ou un flux SSE (`data:`) ; l'en-tête
  `Mcp-Session-Id` rendu à l'initialisation est renvoyé à chaque requête suivante ;
- stdio : un processus local, un message JSON par ligne.

Écrit à la main plutôt qu'avec le SDK `mcp` : ce dernier aurait imposé de reconstruire l'image Docker
(et sa couche CUDA) pour trois méthodes JSON-RPC.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from typing import Any, Protocol

import httpx
from loguru import logger

VERSION_PROTOCOLE = "2025-06-18"
DELAI_SECONDES = 120.0
_CLIENT = {"name": "echohub", "version": "2"}


class ErreurMCP(Exception):
    """Serveur injoignable, réponse illisible ou erreur JSON-RPC."""


class Transport(Protocol):
    async def requete(self, methode: str, params: dict[str, Any]) -> dict[str, Any]: ...
    async def notifier(self, methode: str) -> None: ...
    async def fermer(self) -> None: ...


def _resultat(message: dict[str, Any]) -> dict[str, Any]:
    if "error" in message:
        erreur = message["error"]
        raise ErreurMCP(f"{erreur.get('code')}: {erreur.get('message')}")
    resultat = message.get("result")
    if not isinstance(resultat, dict):
        raise ErreurMCP(f"Réponse sans résultat : {str(message)[:200]}")
    return resultat


def _depuis_sse(texte: str, identifiant: int) -> dict[str, Any]:
    """Le message JSON-RPC portant `identifiant` dans un corps SSE (lignes `data:`)."""
    for ligne in texte.splitlines():
        if ligne.startswith("data:"):
            try:
                message = json.loads(ligne[5:].strip())
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict) and message.get("id") == identifiant:
                return message
    raise ErreurMCP("Flux SSE sans réponse à la requête.")


class TransportHTTP:
    def __init__(self, url: str, entetes: dict[str, str] | None = None) -> None:
        self._url = url
        self._entetes = {"accept": "application/json, text/event-stream", **(entetes or {})}
        self._session: str | None = None
        self._ids = itertools.count(1)
        self._client = httpx.AsyncClient(timeout=DELAI_SECONDES)

    def _en_tetes(self) -> dict[str, str]:
        entetes = dict(self._entetes)
        if self._session:
            entetes["mcp-session-id"] = self._session
            entetes["mcp-protocol-version"] = VERSION_PROTOCOLE
        return entetes

    async def requete(self, methode: str, params: dict[str, Any]) -> dict[str, Any]:
        identifiant = next(self._ids)
        corps = {"jsonrpc": "2.0", "id": identifiant, "method": methode, "params": params}
        try:
            reponse = await self._client.post(self._url, json=corps, headers=self._en_tetes())
        except httpx.HTTPError as exc:
            raise ErreurMCP(f"Serveur MCP injoignable ({self._url}) : {exc}") from exc
        if reponse.status_code >= 400:
            raise ErreurMCP(f"HTTP {reponse.status_code} : {reponse.text[:200]}")
        self._session = reponse.headers.get("mcp-session-id", self._session)
        if "text/event-stream" in reponse.headers.get("content-type", ""):
            return _resultat(_depuis_sse(reponse.text, identifiant))
        return _resultat(reponse.json())

    async def notifier(self, methode: str) -> None:
        try:
            await self._client.post(self._url, json={"jsonrpc": "2.0", "method": methode}, headers=self._en_tetes())
        except httpx.HTTPError as exc:
            logger.warning("Notification MCP {} perdue : {}", methode, exc)

    async def fermer(self) -> None:
        await self._client.aclose()


class TransportStdio:
    def __init__(self, commande: list[str], env: dict[str, str] | None = None) -> None:
        self._commande = commande
        self._env = env
        self._processus: asyncio.subprocess.Process | None = None
        self._ids = itertools.count(1)
        self._verrou = asyncio.Lock()

    async def _demarrer(self) -> asyncio.subprocess.Process:
        if self._processus is None or self._processus.returncode is not None:
            try:
                self._processus = await asyncio.create_subprocess_exec(
                    *self._commande, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, env=self._env)
            except OSError as exc:
                raise ErreurMCP(f"Serveur MCP non lancé ({self._commande[0]}) : {exc}") from exc
        return self._processus

    async def _envoyer(self, message: dict[str, Any]) -> asyncio.subprocess.Process:
        processus = await self._demarrer()
        assert processus.stdin is not None
        try:
            processus.stdin.write((json.dumps(message) + "\n").encode())
            await processus.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            logger.warning("Serveur MCP stdio fermé ({}) : {}", self._commande[0], exc)
            raise ErreurMCP(f"Le serveur MCP s'est arrêté : {exc}") from exc
        return processus

    async def requete(self, methode: str, params: dict[str, Any]) -> dict[str, Any]:
        async with self._verrou:
            identifiant = next(self._ids)
            processus = await self._envoyer({"jsonrpc": "2.0", "id": identifiant, "method": methode, "params": params})
            assert processus.stdout is not None
            while True:
                try:
                    ligne = await asyncio.wait_for(processus.stdout.readline(), DELAI_SECONDES)
                except asyncio.TimeoutError as exc:
                    raise ErreurMCP(f"Pas de réponse du serveur MCP en {DELAI_SECONDES:.0f} s.") from exc
                if not ligne:
                    raise ErreurMCP("Le serveur MCP s'est arrêté.")
                try:
                    message = json.loads(ligne)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict) and message.get("id") == identifiant:
                    return _resultat(message)

    async def notifier(self, methode: str) -> None:
        async with self._verrou:
            await self._envoyer({"jsonrpc": "2.0", "method": methode})

    async def fermer(self) -> None:
        if self._processus is not None and self._processus.returncode is None:
            self._processus.terminate()


class ClientMCP:
    """Un serveur MCP : initialisé une fois, puis interrogé."""

    def __init__(self, nom: str, transport: Transport) -> None:
        self.nom = nom
        self._transport = transport
        self._pret = False

    async def _initialiser(self) -> None:
        if self._pret:
            return
        await self._transport.requete("initialize", {
            "protocolVersion": VERSION_PROTOCOLE, "capabilities": {}, "clientInfo": _CLIENT})
        await self._transport.notifier("notifications/initialized")
        self._pret = True

    async def outils(self) -> list[dict[str, Any]]:
        await self._initialiser()
        resultat = await self._transport.requete("tools/list", {})
        return [o for o in resultat.get("tools", []) if isinstance(o, dict) and o.get("name")]

    async def appeler(self, outil: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """(texte rendu, en erreur ?). Les contenus non textuels sont décrits, jamais transmis."""
        await self._initialiser()
        try:
            resultat = await self._transport.requete("tools/call", {"name": outil, "arguments": arguments})
        except ErreurMCP:
            self._pret = False  # session peut-être expirée : réinitialiser au prochain appel
            raise
        morceaux = []
        for bloc in resultat.get("content", []):
            if isinstance(bloc, dict) and bloc.get("type") == "text":
                morceaux.append(str(bloc.get("text", "")))
            elif isinstance(bloc, dict):
                morceaux.append(f"[{bloc.get('type', 'contenu')} non affichable : le modèle ne voit pas les images]")
        return "\n".join(morceaux), bool(resultat.get("isError"))


__all__ = ["ClientMCP", "ErreurMCP", "TransportHTTP", "TransportStdio"]
