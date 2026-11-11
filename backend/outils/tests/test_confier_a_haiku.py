"""Mode hybride à l'aveugle : Haiku ne reçoit que la tâche et ses propres fichiers ; le harnais pose le code."""

import asyncio
from pathlib import Path

import pytest

from backend.outils import confier_a_haiku, socle
from backend.outils.contrat import ContexteExecution, EchecOutil
from backend.outils.registre import descriptions


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ContexteExecution:
    monkeypatch.setattr(confier_a_haiku.code_aveugle, "canaris", lambda projet: [projet, "acmecorp"])
    return ContexteExecution(conversation_id="conv-x", racine_bac=tmp_path, projet="jeu-secret")


def test_aller_retour_sans_rien_du_projet(monkeypatch: pytest.MonkeyPatch, ctx: ContexteExecution) -> None:
    (ctx.racine_bac / "autre.txt").write_text("données privées acmecorp")
    recus: list[dict] = []

    async def faux(charge: dict) -> dict:
        recus.append(charge)
        return {"texte": "ok", "session": "s-1", "fichiers": {"src/a.js": "export const a = 1;\n"},
                "erreur": False, "duree_ms": 3000}

    monkeypatch.setattr(confier_a_haiku, "_poster", faux)
    sortie = asyncio.run(confier_a_haiku.executer({"task": "write src/a.js exporting a = 1"}, ctx))
    assert (ctx.racine_bac / "src/a.js").read_text() == "export const a = 1;\n" and "src/a.js" in sortie
    (ctx.racine_bac / "src/a.js").write_text("export const a = 2;\n")
    asyncio.run(confier_a_haiku.executer({"tache": "tests fail at /projets/jeu-secret/src/a.js:1"}, ctx))
    premier, second = recus
    assert premier["fichiers"] == {} and premier["session"] is None
    assert second["session"] == "s-1" and second["fichiers"] == {"src/a.js": "export const a = 2;\n"}
    assert "jeu-secret" not in str(recus) and "conv-x" not in str(recus) and "autre.txt" not in str(recus)


def test_fuite_bloquee(ctx: ContexteExecution) -> None:
    with pytest.raises(EchecOutil, match="Refusé avant envoi"):
        asyncio.run(confier_a_haiku.executer({"tache": "build the acmecorp invoice page"}, ctx))
    with pytest.raises(EchecOutil, match="Refusé avant envoi"):
        asyncio.run(confier_a_haiku.executer({"tache": "call https://api.example.org/v1"}, ctx))


def test_refus_hors_projet(tmp_path: Path) -> None:
    with pytest.raises(EchecOutil):
        asyncio.run(confier_a_haiku.executer({"tache": "x"}, ContexteExecution(conversation_id="c", racine_bac=tmp_path)))


def test_socle_hybride_en_mode_projet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESUMEUR_URL", "http://relais")
    monkeypatch.setenv("RESUMEUR_JETON", "x")
    outils = descriptions()
    assert "HYBRID MODE" in socle.construire(outils, projet="p")
    assert "HYBRID MODE" not in socle.construire(outils)


def test_ecriture_locale_refusee_en_mode_hybride(monkeypatch: pytest.MonkeyPatch, ctx: ContexteExecution) -> None:
    from backend.outils import fichiers_bac

    monkeypatch.setenv("RESUMEUR_URL", "http://relais")
    monkeypatch.setenv("RESUMEUR_JETON", "x")
    with pytest.raises(EchecOutil, match="HYBRID MODE"):
        asyncio.run(fichiers_bac._ecrire({"chemin": "big.js", "contenu": "x" * 2000}, ctx))
    asyncio.run(fichiers_bac._ecrire({"chemin": "petit.txt", "contenu": "ok"}, ctx))
    assert (ctx.racine_bac / "petit.txt").read_text() == "ok"
    monkeypatch.setenv("MODE_HYBRIDE", "0")
    asyncio.run(fichiers_bac._ecrire({"chemin": "big.js", "contenu": "x" * 2000}, ctx))
