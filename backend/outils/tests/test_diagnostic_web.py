"""Un échec web dit au modèle la cause, si elle est définitive, et que seule cette adresse est concernée."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from backend.outils import diagnostic_web
from backend.outils.recuperer_page import _fiche_pypi

URL = "https://docs.example.org/api/nope.html"


def test_404_definitif_et_limite_a_cette_adresse() -> None:
    texte = diagnostic_web.echec_http(URL, 404)
    assert "does not exist (HTTP 404)" in texte and "PERMANENT" in texte
    assert "only this address" in texte and "never guess" in texte


def test_5xx_passager() -> None:
    assert "TEMPORARY" in diagnostic_web.echec_http(URL, 502)


def _reseau(monkeypatch: pytest.MonkeyPatch, internet: bool, exc: httpx.HTTPError) -> str:
    async def repond() -> bool:
        return internet
    monkeypatch.setattr(diagnostic_web, "_internet_repond", repond)
    return asyncio.run(diagnostic_web.echec_reseau(URL, exc))


def test_domaine_inexistant(monkeypatch: pytest.MonkeyPatch) -> None:
    texte = _reseau(monkeypatch, True, httpx.ConnectError("[Errno -2] Name or service not known"))
    assert "does not exist (DNS" in texte and "invented or misspelled" in texte


def test_sans_internet_ce_n_est_pas_le_site(monkeypatch: pytest.MonkeyPatch) -> None:
    texte = _reseau(monkeypatch, False, httpx.ConnectError("unreachable"))
    assert "NO Internet connection" in texte and "not about this site" in texte


def test_delai_passager(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "TEMPORARY" in _reseau(monkeypatch, True, httpx.ReadTimeout("slow"))


def test_fiche_pypi_garde_les_vrais_liens() -> None:
    brut = json.dumps({"info": {"name": "httpx", "version": "0.28.1", "summary": "HTTP",
                                "project_urls": {"Documentation": "https://www.python-httpx.org"},
                                "description": "x" * 20_000}})
    fiche = _fiche_pypi(brut) or ""
    assert "Documentation: https://www.python-httpx.org" in fiche and len(fiche) < 400
