"""Adaptateur Strata : cycle de vie par HTTP (/v1/load, /v1/unload, /health), sans serveur réel.

Le transport httpx est remplacé par un faux serveur Strata : on vérifie ce qui est envoyé (route,
clé) et ce que l'adaptateur conclut de chaque réponse.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from backend.inference.engines_adapters import adaptateur_strata as module
from backend.inference.engines_adapters.adaptateur_strata import AdaptateurStrata, SondeStrata, plan_strata
from backend.inference.engines_adapters.contrat import CauseEchec, MoteurSupporte
from backend.inference.engines_adapters.diagnostic import EchecChargement


class _FauxStrata:
    """Répond comme serveur.py de Strata ; `charge` bascule sur /v1/load et /v1/unload."""

    def __init__(self, statut_load: int = 200, corps_load: str = "") -> None:
        self.charge = False
        self.requetes: list[tuple[str, str, str | None]] = []
        self._statut_load, self._corps_load = statut_load, corps_load

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.requetes.append((requete.method, requete.url.path, requete.headers.get("authorization")))
        if requete.url.path == "/v1/load":
            if self._statut_load != 200:
                return httpx.Response(self._statut_load, text=self._corps_load)
            self.charge = True
        if requete.url.path == "/v1/unload":
            self.charge = False
        if requete.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "loaded": self.charge,
                                             "model": "qwen3.8-flash-next-iq2_xs", "max_context": 65536})
        return httpx.Response(200, json={"status": "ok"})


def _brancher(monkeypatch: pytest.MonkeyPatch, faux: Any, jeton: str = "cle") -> AdaptateurStrata:
    monkeypatch.setattr(module, "JETON_STRATA", jeton)
    monkeypatch.setattr(module, "URL_STRATA", "http://strata.test")
    monkeypatch.setattr(module, "lire_vram", lambda: None)
    adaptateur = AdaptateurStrata()

    def client(delai_s: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(faux), timeout=delai_s,
                                 headers={"Authorization": f"Bearer {jeton}"})

    monkeypatch.setattr(adaptateur, "_client", client)
    return adaptateur


def _plan() -> Any:
    return plan_strata(SondeStrata(joignable=True, modele="qwen3.8-flash-next-iq2_xs", contexte=65536))


def test_charger_lit_le_contexte_servi_et_envoie_la_cle(monkeypatch: pytest.MonkeyPatch) -> None:
    faux = _FauxStrata()
    adaptateur = _brancher(monkeypatch, faux)
    etat = asyncio.run(adaptateur.charger(_plan()))
    assert etat.moteur is MoteurSupporte.STRATA and etat.contexte == 65536
    assert ("POST", "/v1/load", "Bearer cle") in faux.requetes


def test_charger_qualifie_un_manque_de_vram(monkeypatch: pytest.MonkeyPatch) -> None:
    adaptateur = _brancher(monkeypatch, _FauxStrata(500, "ExpertCache: cudaMalloc failed: out of memory"))
    with pytest.raises(EchecChargement) as echec:
        asyncio.run(adaptateur.charger(_plan()))
    assert echec.value.diagnostic.cause is CauseEchec.VRAM_INSUFFISANTE


def test_serveur_absent_au_chargement_est_moteur_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé", request=requete)

    adaptateur = _brancher(monkeypatch, refuse)
    with pytest.raises(EchecChargement) as echec:
        asyncio.run(adaptateur.charger(_plan()))
    assert echec.value.diagnostic.cause is CauseEchec.MOTEUR_ABSENT


def test_decharger_libere_meme_sans_chargement_connu(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un Strata resté chargé par un backend précédent doit être libéré : unload toujours envoyé."""
    faux = _FauxStrata()
    faux.charge = True
    adaptateur = _brancher(monkeypatch, faux)
    asyncio.run(adaptateur.decharger())
    assert faux.charge is False


def test_decharger_un_serveur_absent_ne_leve_pas(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé", request=requete)

    asyncio.run(_brancher(monkeypatch, refuse).decharger())


def test_compter_tokens_sans_tokenizer_est_non_mesurable(monkeypatch: pytest.MonkeyPatch) -> None:
    adaptateur = _brancher(monkeypatch, _FauxStrata())
    asyncio.run(adaptateur.charger(_plan()))
    monkeypatch.setattr(module, "_tokenizer", lambda: None)
    comptage = asyncio.run(adaptateur.compter_tokens(["bonjour"]))
    assert comptage.possible is False


def test_plan_strata_vise_le_moteur_strata() -> None:
    plan = _plan()
    assert plan.moteur is MoteurSupporte.STRATA
    assert plan.identifiant_modele == "strata/qwen3.8-flash-next-iq2_xs" and plan.contexte == 65536


def test_sans_configuration_aucun_appel_reseau() -> None:
    """STRATA_URL absent (mode natif, CI) : la sonde répond sans réseau, le déchargement est nul."""
    assert module.URL_STRATA == ""
    assert asyncio.run(module.sonder_serveur()).joignable is False
    asyncio.run(AdaptateurStrata().decharger())
