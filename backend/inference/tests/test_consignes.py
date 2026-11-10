"""Un message glissé pendant le travail est lu à la fin de l'étape, comme dans Claude Code (2026-11-10)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import backend.inference as domaine_inference
from backend.chat.modeles import ParametresEchantillonnage
from backend.chat.port_inference import MessageInference, RequeteGeneration
from backend.inference import MoteurChat, consignes
from backend.inference.engines_adapters.contrat import MessageChat, MorceauGeneration, OptionsGeneration
from backend.outils import registre
from backend.outils.contrat import ContexteExecution, DescriptionOutil, Outil

APPEL = "<function=read_file>\n<parameter=path>\napp.py\n</parameter>\n</function>"


class _Modele:
    def __init__(self, scenario: list[str], glisser_au_tour: int) -> None:
        self.scenario, self.vus, self.glisser_au_tour = scenario, [], glisser_au_tour

    def generer(self, messages: Sequence[MessageChat], options: OptionsGeneration,
                outils: Sequence[dict[str, Any]] | None = None) -> AsyncIterator[MorceauGeneration]:
        self.vus.append(list(messages))
        if len(self.vus) == self.glisser_au_tour:
            consignes.deposer("glisse", "k1", "Utilise pnpm, pas npm.")
        texte = self.scenario.pop(0) if self.scenario else "Bilan : fait."
        return self._flux(texte)

    async def _flux(self, texte: str) -> AsyncIterator[MorceauGeneration]:
        yield MorceauGeneration(type="token", contenu=texte)


def _jouer(monkeypatch: Any, scenario: list[str], glisser_au_tour: int) -> tuple[_Modele, str]:
    async def lire(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
        return "print(1)"

    outil = Outil(description=DescriptionOutil(nom="lire_fichier", description="test",
                                               parametres={"type": "object", "properties": {}}), executer=lire)
    monkeypatch.setitem(registre._OUTILS, "lire_fichier", outil)
    modele = _Modele(scenario, glisser_au_tour)
    monkeypatch.setattr(domaine_inference, "superviseur", modele)
    recu: list[str] = []

    async def consommer() -> None:
        requete = RequeteGeneration(messages=[MessageInference(role="user", contenu="corrige app.py")],
                                    parametres=ParametresEchantillonnage(), conversation_id="glisse")
        async for morceau in MoteurChat().generer(requete):
            if isinstance(morceau.get("texte"), str):
                recu.append(morceau["texte"])

    asyncio.run(consommer())
    return modele, "".join(recu)


def _lu(messages: list[MessageChat]) -> bool:
    return any(m.role == "user" and "Utilise pnpm" in str(m.content) for m in messages)


def test_lu_a_la_fin_de_l_etape_d_outil(monkeypatch: Any) -> None:
    modele, texte = _jouer(monkeypatch, [f"Je lis.{APPEL}", "Bilan : app.py affiche 1, les dépendances sont installées avec pnpm et tout passe."], glisser_au_tour=1)
    assert len(modele.vus) == 2 and _lu(modele.vus[1])
    assert "<consigne>id:k1\nUtilise pnpm" in texte
    assert consignes.prendre("glisse") == []


def test_glisse_pendant_la_reponse_finale_le_modele_reprend(monkeypatch: Any) -> None:
    scenario = [f"Je lis.{APPEL}", "Bilan : app.py affiche 1 comme attendu, rien d'autre à corriger dans ce fichier.",
                "Bilan : dépendances réinstallées avec pnpm comme demandé, app.py affiche toujours 1."]
    modele, _ = _jouer(monkeypatch, scenario, glisser_au_tour=2)
    assert len(modele.vus) == 3 and _lu(modele.vus[2])
    assert any(m.role == "assistant" and "comme attendu" in str(m.content) for m in modele.vus[2])
