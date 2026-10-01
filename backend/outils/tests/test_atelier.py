"""Preuves du client de l'atelier (`atelier.py`) — la frontière réseau, `httpx` mocké.

On ne lance pas le conteneur atelier ici : on vérifie ce que le client ENVOIE (URL, jeton en
en-tête, corps) et comment il se comporte quand l'atelier répond mal ou pas du tout. Le jeton, seul
rempart devant un service qui exécute du shell root, doit partir en en-tête et jamais dans le corps.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from backend.core.config import reset_settings_cache
from backend.outils import atelier


@pytest.fixture
def jeton_configure(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("ATELIER_URL", "http://echohub-atelier:8080")
    monkeypatch.setenv("ATELIER_JETON", "jeton-de-test")
    reset_settings_cache()
    yield "jeton-de-test"
    reset_settings_cache()


def test_executer_commande_envoie_url_jeton_et_corps(
    jeton_configure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    captures: dict[str, Any] = {}

    def _post(url: str, **kwargs: Any) -> httpx.Response:
        captures["url"] = url
        captures["json"] = kwargs["json"]
        captures["headers"] = kwargs["headers"]
        corps = {"code_retour": 0, "sortie": "ok", "erreur": "", "duree_s": 1.5, "tue": False}
        return httpx.Response(200, json=corps, request=httpx.Request("POST", url))

    monkeypatch.setattr(atelier.httpx, "post", _post)

    reponse = atelier.executer_commande("echo ok", "conv-42", 600)

    assert captures["url"] == "http://echohub-atelier:8080/executer/commande"
    assert captures["json"] == {"commande": "echo ok", "sous_dossier": "conv-42", "timeout_s": 600,
                                "racine": "workspace"}
    assert captures["headers"]["X-Atelier-Jeton"] == jeton_configure
    assert "jeton" not in captures["json"], "le jeton ne doit jamais partir dans le corps"
    assert reponse.code_retour == 0 and reponse.sortie == "ok"


def test_atelier_non_joignable_leve_avec_message_actionnable(
    jeton_configure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _post(url: str, **_: Any) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=httpx.Request("POST", url))

    monkeypatch.setattr(atelier.httpx, "post", _post)

    with pytest.raises(atelier.AtelierInjoignable) as exc:
        atelier.executer_python("print(1)", "conv-42", 600)
    assert "docker compose up -d echohub-atelier" in str(exc.value)


def test_reponse_non_200_est_traitee_comme_injoignable(
    jeton_configure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _post(url: str, **_: Any) -> httpx.Response:
        return httpx.Response(401, text="jeton invalide", request=httpx.Request("POST", url))

    monkeypatch.setattr(atelier.httpx, "post", _post)

    with pytest.raises(atelier.AtelierInjoignable) as exc:
        atelier.executer_commande("echo ok", "conv-42", 600)
    assert "401" in str(exc.value)
