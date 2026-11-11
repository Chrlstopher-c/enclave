"""Progression : état d'une commande, étapes rendues, battement, résumé local avec débit."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest

from backend.commandes import progression
from backend.commandes.progression import EtatCommande, ProgressionCompaction, battements
from backend.inference import resume_compaction
from backend.inference.engines_adapters.contrat import MessageChat, MorceauGeneration


def test_les_etapes_suivent_la_progression_et_se_figent_a_la_fin() -> None:
    etat = EtatCommande(id="c1", nom="compact")
    etat.progression.appliquer({"etape": "resume", "resumeur": "local"})
    rendu = etat.snapshot()
    assert [e["etat"] for e in rendu["etapes"]] == ["fait", "en_cours", "a_faire"]
    assert rendu["resumeur"] == "local" and rendu["etat"] == "en_cours"

    etat.terminer()
    fin = etat.snapshot()
    assert [e["etat"] for e in fin["etapes"]] == ["fait", "fait", "fait"]
    duree = fin["duree_ms"]
    assert etat.snapshot()["duree_ms"] == duree, "la durée s'arrête à la fin"


def test_un_echec_garde_son_message_actionnable() -> None:
    etat = EtatCommande(id="c2", nom="compact")
    etat.echouer("Compaction impossible -> Ouvrir un modèle.")
    rendu = etat.snapshot()
    assert rendu["etat"] == "echec" and rendu["erreur"].endswith("Ouvrir un modèle.")


def test_le_battement_rend_la_main_tant_que_la_tache_tourne(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(progression, "INTERVALLE_BATTEMENT_S", 0.01)

    async def lent() -> None:
        await asyncio.sleep(0.05)

    async def scenario() -> int:
        tache = asyncio.ensure_future(lent())
        return len([_ async for _ in battements(tache)])

    assert asyncio.run(scenario()) >= 2


def test_le_rappel_ne_change_que_les_cles_qu_il_donne() -> None:
    progression_ = ProgressionCompaction()
    progression_.appliquer({"etape": "resume"})
    progression_.appliquer({"tokens": 40, "tokens_par_seconde": 21.5})
    assert progression_.etape == "resume" and progression_.resumeur is None
    assert progression_.tokens == 40 and progression_.tokens_par_seconde == 21.5


class _SuperviseurLocal:
    async def generer(self, messages: Sequence[MessageChat], options: Any,
                      outils: Any = None) -> AsyncIterator[MorceauGeneration]:
        for morceau in ("Le ", "résumé ", "final"):
            await asyncio.sleep(0.01)
            yield MorceauGeneration(type="token", contenu=morceau)
        yield MorceauGeneration(type="fin", raison_arret="stop")


def test_le_resume_local_publie_le_resumeur_et_le_debit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resume_compaction, "superviseur", _SuperviseurLocal())
    vus: list[dict[str, Any]] = []

    async def suivi(details: dict[str, Any]) -> None:
        vus.append(details)

    texte = asyncio.run(resume_compaction.produire_resume("échanges", "", "", 256, suivi=suivi))
    assert texte == "Le résumé final"
    assert {"resumeur": "local"} in vus
    dernier = [v for v in vus if "tokens" in v][-1]
    assert dernier["tokens"] == 3 and dernier["tokens_par_seconde"] > 0
