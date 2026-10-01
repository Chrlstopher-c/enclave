"""Une annonce sans appel est relancée en rouvrant le tour sur `<tool_call>`, sans consigne ni écho."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import backend.inference as domaine_inference
from backend.chat.modeles import ParametresEchantillonnage
from backend.chat.port_inference import MessageInference, RequeteGeneration
from backend.inference import MoteurChat
from backend.inference.engines_adapters.contrat import MessageChat, MorceauGeneration, OptionsGeneration
from backend.inference.pre_remplissage import OUVERTURE_APPEL, sans_echo
from backend.outils import registre
from backend.outils.contrat import ContexteExecution, DescriptionOutil, Outil

ANNONCE = "J'ai compris le problème dans le module principal. Je vais lire le fichier main.py."
APPEL = '<tool_call>{"name": "lire_fichier", "arguments": {"chemin": "main.py"}}</tool_call>'
BILAN = "Le fichier est lu : la fonction principale appelle une méthode absente, je l'ai notée ici."


class _SuperviseurPreRemplissable:
    """Annonce au tour 1 ; pré-rempli, renvoie l'écho puis l'appel ; enfin un bilan."""

    def __init__(self) -> None:
        self.tours: list[list[MessageChat]] = []

    def accepte_pre_remplissage(self) -> bool:
        return True

    def generer(self, messages: Sequence[MessageChat], options: OptionsGeneration,
                outils: Sequence[dict[str, Any]] | None = None) -> AsyncIterator[MorceauGeneration]:
        self.tours.append(list(messages))
        return self._flux(len(self.tours), messages[-1])

    async def _flux(self, rang: int, dernier: MessageChat) -> AsyncIterator[MorceauGeneration]:
        if rang == 1:
            contenu = ANNONCE
        elif dernier.role == "assistant":
            contenu = f"<think>\n\n</think>\n\n{ANNONCE}\n{APPEL}"
        else:
            contenu = BILAN
        yield MorceauGeneration(type="token", contenu=contenu)
        yield MorceauGeneration(type="fin", raison_arret="stop")


def _outil_lire() -> Outil:
    async def executer(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
        return "def main(): appeler()"

    return Outil(description=DescriptionOutil(nom="lire_fichier", description="Test.",
                                              parametres={"type": "object", "properties": {}}), executer=executer)


def test_annonce_relancee_par_pre_remplissage(monkeypatch: Any) -> None:
    superviseur = _SuperviseurPreRemplissable()
    monkeypatch.setattr(registre, "_OUTILS", {"lire_fichier": _outil_lire()})
    monkeypatch.setattr(domaine_inference, "superviseur", superviseur)

    async def lire() -> str:
        textes: list[str] = []
        async for morceau in MoteurChat().generer(RequeteGeneration(
                messages=[MessageInference(role="user", contenu="corrige main.py")],
                parametres=ParametresEchantillonnage(), conversation_id="conv-pre")):
            if isinstance(morceau.get("texte"), str):
                textes.append(morceau["texte"])
        return "".join(textes)

    sortie = asyncio.run(lire())
    assert len(superviseur.tours) == 3
    pre_rempli = superviseur.tours[1][-1]
    assert pre_rempli.role == "assistant" and pre_rempli.content.endswith(OUVERTURE_APPEL)
    assert all(m.role != "user" or "corrige" in str(m.content) for m in superviseur.tours[1]), "aucune consigne"
    assert sortie.count(ANNONCE) == 1, "l'écho du pré-remplissage n'est pas réaffiché"
    roles = [m.role for m in superviseur.tours[2]]
    assert "assistant" in roles and roles[-1] == "tool"
    assert not any(m.role == "assistant" and str(m.content).endswith(OUVERTURE_APPEL) for m in superviseur.tours[2])
    assert BILAN in sortie


def test_sans_echo_laisse_passer_un_flux_qui_ne_reprend_pas_l_annonce() -> None:
    async def flux() -> AsyncIterator[dict[str, Any]]:
        for texte in ("<think>\n\n</think>\n\n", "Autre ", "chose."):
            yield {"texte": texte}

    async def lire() -> str:
        return "".join([m["texte"] async for m in sans_echo(flux(), "Je vais lire le fichier.")])

    assert asyncio.run(lire()) == "Autre chose."
