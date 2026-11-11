"""Code à l'aveugle : aller-retour des noms, garde avant envoi, outil complet avec relais simulé."""

import asyncio
from pathlib import Path

import pytest

from backend.outils import code_aveugle, deleguer_code
from backend.outils.code_aveugle import Spec
from backend.outils.contrat import ContexteExecution, EchecOutil

SPEC = Spec(langage="python", signature="def total_facture(lignes: list[Ligne], remise: float) -> float",
            comportement="Somme des lignes de total_facture, moins remise en pourcentage.",
            tests=["total_facture([], 0.1) == 0.0"])


def test_aller_retour_des_noms() -> None:
    anonyme, table = code_aveugle.anonymiser(SPEC)
    assert "total_facture" not in "\n".join(anonyme.textes())
    assert "Ligne" not in anonyme.signature and "remise" not in anonyme.signature
    assert anonyme.signature.startswith("def fn_1(") and "list[T1]" in anonyme.signature
    code = "def fn_1(v_1: list[T1], v_2: float) -> float:\n    return sum(x.prix for x in v_1) * (1 - v_2)"
    retour = code_aveugle.rehydrater(code, table)
    assert retour.startswith("def total_facture(lignes: list[Ligne], remise: float)")
    assert "for x in lignes" in retour


def test_garde_bloque_les_fuites() -> None:
    sale = Spec(langage="python", signature="def f(a: int) -> int",
                comportement="Lit https://api.exemple.fr et /home/chris/projet/data.csv pour stocklab")
    trouve = code_aveugle.fuites(sale, ["stocklab"])
    assert any("URL" in t for t in trouve) and any("chemin" in t for t in trouve)
    assert any("stocklab" in t for t in trouve)
    assert code_aveugle.fuites(Spec("python", "def f(a: int) -> int", "Rend a / 2 arrondi"), []) == []


def _contexte(tmp_path: Path) -> ContexteExecution:
    return ContexteExecution(conversation_id="c", racine_bac=tmp_path, projet="stocklab")


def test_outil_envoie_anonyme_et_restaure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    envoye: list[str] = []

    async def faux_relais(corps: str) -> str:
        envoye.append(corps)
        return "```python\ndef fn_1(v_1: list[T1], v_2: float) -> float:\n    return 0.0\n```"

    monkeypatch.setattr(deleguer_code, "_demander", faux_relais)
    monkeypatch.setattr(deleguer_code, "_canaris", lambda contexte: ["stocklab"])
    sortie = asyncio.run(deleguer_code.executer(
        {"language": "python", "signature": SPEC.signature, "behavior": SPEC.comportement, "tests": SPEC.tests},
        _contexte(tmp_path)))
    assert "total_facture" not in envoye[0] and "fn_1" in envoye[0]
    assert "def total_facture(lignes: list[Ligne], remise: float)" in sortie


def test_outil_refuse_une_fuite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(deleguer_code, "_canaris", lambda contexte: ["stocklab"])
    with pytest.raises(EchecOutil, match="Refusé avant envoi"):
        asyncio.run(deleguer_code.executer(
            {"langage": "python", "signature": "def f(a: int) -> int", "comportement": "pour stocklab"},
            _contexte(tmp_path)))
