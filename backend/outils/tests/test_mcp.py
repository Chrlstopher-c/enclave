"""Client MCP : un vrai serveur stdio en sous-processus, et l'analyse des réponses SSE du transport HTTP."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from backend.core.config import reset_settings_cache
from backend.outils.contrat import ContexteExecution, EchecOutil
from backend.outils.mcp_client import ErreurMCP, _depuis_sse
from backend.outils.mcp_registre import OUTIL_MCP_APPELER, OUTIL_MCP_OUTILS, serveurs_connus

SERVEUR = r'''
import json, sys
for ligne in sys.stdin:
    m = json.loads(ligne)
    if "id" not in m:
        continue
    if m["method"] == "initialize":
        r = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "eco"}}
    elif m["method"] == "tools/list":
        r = {"tools": [{"name": "echo", "description": "Renvoie le texte.\nDétail.",
                        "inputSchema": {"type": "object", "properties": {"texte": {"type": "string"}}}}]}
    elif m["params"]["name"] == "echo":
        r = {"content": [{"type": "text", "text": "écho: " + m["params"]["arguments"]["texte"]},
                         {"type": "image", "data": "xx"}]}
    else:
        r = {"content": [{"type": "text", "text": "outil inconnu"}], "isError": True}
    print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}), flush=True)
'''


@pytest.fixture
def contexte(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ContexteExecution:
    agent = tmp_path / "agent"
    agent.mkdir()
    (tmp_path / "serveur.py").write_text(SERVEUR)
    config = {"mcpServers": {"eco": {"command": sys.executable, "args": [str(tmp_path / "serveur.py")],
                                     "description": "serveur de test"}}}
    (agent / "mcp.json").write_text(json.dumps(config))
    monkeypatch.setenv("ECHOHUB_AGENT_DIR", str(agent))
    reset_settings_cache()
    yield ContexteExecution(conversation_id="c", racine_bac=tmp_path)
    reset_settings_cache()


def _lancer(outil, arguments: dict, contexte: ContexteExecution) -> str:
    return asyncio.run(outil.executer(arguments, contexte))


def test_liste_schema_et_appel_par_stdio(contexte: ContexteExecution) -> None:
    liste = _lancer(OUTIL_MCP_OUTILS, {"serveur": "eco"}, contexte)
    assert liste.startswith("1 outil(s)") and "- echo: Renvoie le texte." in liste
    schema = _lancer(OUTIL_MCP_OUTILS, {"serveur": "eco", "outil": "echo"}, contexte)
    assert '"texte"' in schema
    sortie = _lancer(OUTIL_MCP_APPELER, {"serveur": "eco", "outil": "echo", "arguments": {"texte": "salut"}}, contexte)
    assert "écho: salut" in sortie and "ne voit pas les images" in sortie
    assert any("echo" in ligne for _, lignes in serveurs_connus() for ligne in lignes)


def test_erreurs_rendues_en_echec(contexte: ContexteExecution) -> None:
    with pytest.raises(EchecOutil, match="outil inconnu"):
        _lancer(OUTIL_MCP_APPELER, {"serveur": "eco", "outil": "absent"}, contexte)
    with pytest.raises(EchecOutil, match="inconnu"):
        _lancer(OUTIL_MCP_OUTILS, {"serveur": "fantome"}, contexte)


def test_reponse_sse_du_transport_http() -> None:
    corps = 'event: message\ndata: {"jsonrpc":"2.0","id":3,"result":{"tools":[]}}\n\n'
    assert _depuis_sse(corps, 3)["result"] == {"tools": []}
    with pytest.raises(ErreurMCP):
        _depuis_sse(corps, 4)
