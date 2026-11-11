"""Les URL locales passées à un serveur MCP visent l'atelier, pas le conteneur du serveur."""

from backend.outils import adresse_atelier


def test_localhost_reecrit_vers_atelier(monkeypatch) -> None:
    monkeypatch.setattr(adresse_atelier, "hote_atelier", lambda: "echohub-atelier")
    sortie, note = adresse_atelier.vers_atelier({"url": "http://localhost:8123/?t=2"})
    assert sortie == {"url": "http://echohub-atelier:8123/?t=2"}
    assert note and "echohub-atelier" in note
    code, _ = adresse_atelier.vers_atelier({"code": "await page.goto('http://127.0.0.1:5173/')"})
    assert code["code"] == "await page.goto('http://echohub-atelier:5173/')"


def test_rien_a_reecrire(monkeypatch) -> None:
    monkeypatch.setattr(adresse_atelier, "hote_atelier", lambda: "echohub-atelier")
    parametres = {"url": "http://echohub-atelier:8123/", "ref": "e3"}
    assert adresse_atelier.vers_atelier(parametres) == (parametres, None)
    assert adresse_atelier.vers_atelier({"url": "http://localhostile.com/"})[1] is None
