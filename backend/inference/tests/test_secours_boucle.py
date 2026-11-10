"""Une boucle de relectures est soignée par compaction forcée, une fois ; la suivante arrête (« TUI », 2026-11-10)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import backend.inference as domaine_inference
from backend.chat.modeles import ParametresEchantillonnage
from backend.chat.port_inference import MessageInference, RequeteGeneration
from backend.inference import CONSIGNE_APRES_BOUCLE, MoteurChat
from backend.inference.engines_adapters.contrat import MessageChat, MorceauGeneration, OptionsGeneration
from backend.outils import registre
from backend.outils.contrat import ContexteExecution, DescriptionOutil, Outil

APPEL = "Je relis.<function=read_file>\n<parameter=path>\napp.py\n</parameter>\n</function>"
CONTENU = "\n".join(f"ligne {n} de app.py" for n in range(30))


class _Modele:
    def __init__(self, tours_en_boucle: int) -> None:
        self.reste, self.vus = tours_en_boucle, []

    def generer(self, messages: Sequence[MessageChat], options: OptionsGeneration,
                outils: Sequence[dict[str, Any]] | None = None) -> AsyncIterator[MorceauGeneration]:
        self.vus.append(list(messages))
        self.reste -= 1
        texte = APPEL if self.reste >= 0 else "Bilan : app.py relu, le worker démarre dans on_mount, rien à corriger."
        return self._flux(texte)

    async def _flux(self, texte: str) -> AsyncIterator[MorceauGeneration]:
        yield MorceauGeneration(type="token", contenu=texte)


def _jouer(monkeypatch: Any, tours: int, compaction_reussie: bool) -> tuple[_Modele, str, list[int]]:
    async def lire(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
        return CONTENU

    outil = Outil(description=DescriptionOutil(nom="lire_fichier", description="t",
                                               parametres={"type": "object", "properties": {}}), executer=lire)
    monkeypatch.setitem(registre._OUTILS, "lire_fichier", outil)
    forcees: list[int] = []

    async def compacter(messages: list[MessageChat], etat: Any, etape_terminee: bool, taches: str = "",
                        forcer: bool = False) -> str | None:
        if forcer:
            forcees.append(1)
            return "\n*[Contexte compacté]*\n" if compaction_reussie else None
        return None

    monkeypatch.setattr(domaine_inference, "compacter_si_besoin", compacter)
    modele = _Modele(tours)
    monkeypatch.setattr(domaine_inference, "superviseur", modele)
    texte: list[str] = []

    async def consommer() -> None:
        requete = RequeteGeneration(messages=[MessageInference(role="user", contenu="corrige app.py")],
                                    parametres=ParametresEchantillonnage(), conversation_id="secours")
        async for m in MoteurChat().generer(requete):
            if isinstance(m.get("texte"), str):
                texte.append(m["texte"])

    asyncio.run(consommer())
    return modele, "".join(texte), forcees


def test_boucle_soignee_puis_reprise(monkeypatch: Any) -> None:
    modele, texte, forcees = _jouer(monkeypatch, tours=7, compaction_reussie=True)
    assert forcees == [1] and "Contexte compacté" in texte
    assert any(m.role == "user" and m.content == CONSIGNE_APRES_BOUCLE for m in modele.vus[-1])
    assert "Arrêt automatique" not in texte and "Bilan" in texte


def test_sans_compaction_possible_l_arret_est_explique(monkeypatch: Any) -> None:
    _, texte, forcees = _jouer(monkeypatch, tours=20, compaction_reussie=False)
    assert forcees == [1] and "Arrêt automatique" in texte


def test_les_redites_ne_s_empilent_pas_au_contexte(monkeypatch: Any) -> None:
    """Une seule trace de la lecture et une seule consigne, quel que soit le nombre de redites."""
    from backend.inference import MARQUE_REDITE

    modele, _, _ = _jouer(monkeypatch, tours=4, compaction_reussie=True)
    dernier = modele.vus[-1]
    assert sum(1 for m in dernier if m.role == "tool") == 1, [m.role for m in dernier]
    assert sum(1 for m in dernier if m.role == "user" and str(m.content).startswith(MARQUE_REDITE)) == 1
    assert "corrige app.py" in str(dernier[0].content)
