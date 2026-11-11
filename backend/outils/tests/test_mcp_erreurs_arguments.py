"""Un appel MCP refusé pour arguments invalides renvoie le schéma exact de l'outil."""

import asyncio

from backend.outils import mcp_registre


class _Client:
    async def outils(self) -> list[dict]:
        return [{"name": "browser_evaluate", "description": "Evaluate JS",
                 "inputSchema": {"properties": {"function": {"type": "string"}}}}]


def test_schema_joint_aux_arguments_invalides(monkeypatch) -> None:
    monkeypatch.setattr(mcp_registre, "_client", lambda nom: _Client())
    texte = asyncio.run(mcp_registre._schema_si_arguments(
        "playwright", "browser_evaluate", 'Invalid arguments for tool "browser_evaluate"'))
    assert '"function"' in texte
    assert asyncio.run(mcp_registre._schema_si_arguments("playwright", "browser_evaluate", "Timeout")) == ""


def test_note_capture() -> None:
    assert "cannot see" in (mcp_registre._note_image("browser_take_screenshot") or "")
    assert mcp_registre._note_image("browser_snapshot") is None
