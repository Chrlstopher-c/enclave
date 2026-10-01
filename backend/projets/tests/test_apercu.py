"""Aperçu : le backend pointe le relais de l'atelier et rend l'URL à ouvrir, sans relayer d'octet."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from backend.core.config import reset_settings_cache
from backend.projets import apercu
from backend.projets.racine import ProjetInvalide


@pytest.fixture
def projet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    (tmp_path / "app").mkdir()
    monkeypatch.setenv("ECHOHUB_PROJETS_RACINE", str(tmp_path))
    monkeypatch.setenv("ATELIER_APERCU_URL", "http://127.0.0.1:9999")
    reset_settings_cache()
    yield "app"
    reset_settings_cache()


def _atelier(monkeypatch: pytest.MonkeyPatch, gestion: httpx.MockTransport) -> None:
    client = httpx.Client(transport=gestion)
    monkeypatch.setattr(httpx, "get", client.get)
    monkeypatch.setattr(httpx, "post", client.post)


def test_pointer_rend_l_url_et_les_ports(projet: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def gestion(requete: httpx.Request) -> httpx.Response:
        assert requete.url.path == "/apercu" and requete.method == "POST"
        return httpx.Response(200, json={"port": 8000, "ports": [8000, 5173]})

    _atelier(monkeypatch, httpx.MockTransport(gestion))
    etat = apercu.pointer(projet, 8000)
    assert etat.port == 8000 and etat.ports == [8000, 5173] and etat.url == "http://127.0.0.1:9999/"


def test_port_reserve_refuse(projet: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _atelier(monkeypatch, httpx.MockTransport(lambda _: httpx.Response(409, json={"detail": "Port 8080 réservé"})))
    with pytest.raises(apercu.ApercuRefuse, match="réservé"):
        apercu.pointer(projet, 8080)


def test_atelier_injoignable(projet: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def gestion(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé", request=requete)

    _atelier(monkeypatch, httpx.MockTransport(gestion))
    with pytest.raises(apercu.ApercuIndisponible):
        apercu.lire(projet)


def test_projet_inconnu(projet: str) -> None:
    with pytest.raises(ProjetInvalide):
        apercu.lire("absent")
