"""Boucle « je vais corriger… » (Ornith 9B, 2026-11-10) : relances empilées, appels invisibles.

Trois causes corrigées, chacune vérifiée ici sur la boucle réelle (moteur factice) :
- une relance REMPLACE la précédente : le contexte ne garde qu'une tentative ratée ;
- un modèle qui radote est clos après une seule relance, au lieu de dix ;
- le tour d'assistant porte ses appels au format natif, reliés aux résultats par leur identifiant.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import backend.inference as domaine_inference
from backend.chat.modeles import ParametresEchantillonnage
from backend.chat.port_inference import MessageInference, RequeteGeneration
from backend.inference import MoteurChat
from backend.inference.engines_adapters.contrat import MessageChat, MorceauGeneration, OptionsGeneration
from backend.outils import registre
from backend.outils.contrat import ContexteExecution, DescriptionOutil, Outil

ANNONCES = ("Je vais corriger l'application.", "I need to fix the import. Let me read the file first.")
APPEL = "<function=lire_fichier>\n<parameter=chemin>\napp.py\n</parameter>\n</function>"


class _Modele:
    def __init__(self, scenario: list[str]) -> None:
        self.scenario, self.vus = scenario, []

    def generer(self, messages: Sequence[MessageChat], options: OptionsGeneration,
                outils: Sequence[dict[str, Any]] | None = None) -> AsyncIterator[MorceauGeneration]:
        self.vus.append(list(messages))
        texte = self.scenario.pop(0) if self.scenario else "Bilan : fait."
        return self._flux(texte)

    async def _flux(self, texte: str) -> AsyncIterator[MorceauGeneration]:
        yield MorceauGeneration(type="token", contenu=texte)


def _jouer(monkeypatch: Any, scenario: list[str]) -> _Modele:
    async def lire(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
        return "print(1)"

    outil = Outil(description=DescriptionOutil(nom="lire_fichier", description="test",
                                               parametres={"type": "object", "properties": {}}), executer=lire)
    monkeypatch.setitem(registre._OUTILS, "lire_fichier", outil)
    modele = _Modele(scenario)
    monkeypatch.setattr(domaine_inference, "superviseur", modele)

    async def consommer() -> None:
        requete = RequeteGeneration(messages=[MessageInference(role="user", contenu="corrige app.py")],
                                    parametres=ParametresEchantillonnage(), conversation_id="relances")
        async for _ in MoteurChat().generer(requete):
            pass

    asyncio.run(consommer())
    return modele


def _annonces(messages: list[MessageChat]) -> int:
    return sum(1 for m in messages if m.role == "assistant" and any(a in str(m.content) for a in ANNONCES))


def test_une_seule_tentative_ratee_reste_au_contexte(monkeypatch: Any) -> None:
    modele = _jouer(monkeypatch, [ANNONCES[0], ANNONCES[1], ANNONCES[0], ANNONCES[1]])
    assert len(modele.vus) >= 3
    assert all(_annonces(vus) <= 1 for vus in modele.vus), [_annonces(v) for v in modele.vus]


def test_le_radotage_est_clos_apres_une_relance(monkeypatch: Any) -> None:
    modele = _jouer(monkeypatch, [ANNONCES[0]] * 20)
    assert len(modele.vus) <= 8, f"{len(modele.vus)} tours : la boucle n'a pas été coupée"


def test_l_appel_part_au_format_natif_relie_a_son_resultat(monkeypatch: Any) -> None:
    modele = _jouer(monkeypatch, [f"Je lis le fichier.{APPEL}", "Bilan : app.py affiche 1."])
    suite = modele.vus[1]
    appelant = next(m for m in suite if m.role == "assistant" and m.tool_calls)
    resultat = next(m for m in suite if m.role == "tool")
    assert appelant.tool_calls[0]["function"]["name"] == "read_file", "le moteur voit le nom public"
    assert resultat.tool_call_id == appelant.tool_calls[0]["id"]
    assert "<function=" not in str(appelant.content), "le balisage brut ne repart toujours pas en prose"
