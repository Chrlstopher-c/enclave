"""Après un « continue », le modèle retrouve ce que ses outils ont rendu et n'est pas resservi en double.

Scénario mesuré (Chris, 2026-11-10) : le modèle lit des fichiers, s'arrête ; l'utilisateur écrit
« continue » ; le modèle relit tout. Ces tests rejouent ce scénario sans moteur réel.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

import backend.outils as outils
from backend.inference import _executer_appels, _messages_depuis, harnais
from backend.inference.memoire_travail import (
    REDITES_ARRET,
    REDITES_INSISTANTES,
    Segment,
    avis_redite,
    budgeter,
    deplier,
    redite,
)
from backend.outils.contrat import ContexteExecution, ResultatOutil

FICHIER = "\n".join(f"ligne {n} du module app.py" for n in range(40))


def _bloc(entree: str, sortie: str, echec: bool = False) -> str:
    ouvrante = '<sortie etat="echec">' if echec else "<sortie>"
    return f"<outil><entree>{entree}</entree>{ouvrante}{sortie}</sortie></outil><etape-fin/>"


class _Message:
    def __init__(self, role: str, contenu: str) -> None:
        self.role, self.contenu, self.pieces = role, contenu, []


HISTORIQUE = [
    _Message("user", "Corrige le bug de app.py"),
    _Message("assistant", f"Je lis le fichier.{_bloc('lire_fichier(chemin : app.py)', FICHIER)}Je m'arrête là."),
    _Message("user", "continue"),
]


def test_deplier_rend_la_suite_du_tour_sans_balisage() -> None:
    segments = deplier(f"Je lis.{_bloc('lire_fichier(chemin : a.py)', 'x')}"
                       f"{_bloc('executer_commande(commande : ls)', 'boom', echec=True)}Fini.")
    assert [s.role for s in segments] == ["assistant", "tool", "tool", "assistant"]
    assert segments[1].annonce == "lire_fichier(chemin : a.py)" and segments[2].echec


def test_un_resultat_ne_suit_jamais_directement_l_utilisateur() -> None:
    # Tour arrêté sur un appel : il finit sur le résultat, sans tour d'assistant vide inventé.
    segments = deplier(_bloc("lire_fichier(chemin : a.py)", "x"))
    assert [s.role for s in segments] == ["assistant", "tool"]


def test_les_sorties_d_avant_le_continue_restent_au_contexte() -> None:
    convertis = _messages_depuis(HISTORIQUE)
    assert [m.role for m in convertis] == ["user", "assistant", "tool", "assistant", "user"]
    assert FICHIER in str(convertis[2].content)
    assert "app.py" in str(convertis[2].content), "le modèle doit savoir QUEL fichier il a lu"
    assert all("<outil" not in str(m.content) and "relire" not in str(m.content) for m in convertis)


def test_au_dela_du_budget_les_plus_anciennes_deviennent_une_ligne() -> None:
    segments = [Segment("tool", "a" * 30, "lire_fichier(chemin : vieux.py)"),
                Segment("tool", "b" * 30, "lire_fichier(chemin : recent.py)")]
    vieux, recent = budgeter(segments, budget=40)
    assert "b" * 30 in recent.contenu
    assert "vieux.py" in vieux.contenu and "a" * 30 not in vieux.contenu


def test_redite_compare_la_sortie_pas_l_appel() -> None:
    contexte = _messages_depuis(HISTORIQUE)
    assert redite(FICHIER, contexte)
    assert not redite(FICHIER + "\nligne ajoutée", contexte), "un fichier modifié repasse en entier"
    assert not redite("Écrit.", contexte), "une sortie courte n'est jamais remplacée"


def test_l_avis_devient_une_consigne_d_arret_quand_le_modele_insiste() -> None:
    assert "Stop reading" not in avis_redite("lire_fichier(chemin : a.py)", 1)
    assert "Stop reading" in avis_redite("lire_fichier(chemin : a.py)", REDITES_INSISTANTES)


def _rejouer(monkeypatch: pytest.MonkeyPatch, contenu_disque: str, appels: int,
             historique: list[_Message] | None = None) -> tuple[list[str], int]:
    """Le modèle relit app.py `appels` fois après « continue » ; rend ce qu'il reçoit et les redites."""

    async def lire(nom: str, arguments: Any, contexte: ContexteExecution) -> ResultatOutil:
        return ResultatOutil(nom=nom, succes=True, texte=contenu_disque)

    monkeypatch.setattr(outils, "executer", lire)
    messages = _messages_depuis(HISTORIQUE if historique is None else historique)
    etat = harnais.EtatBoucle(harnais=harnais.FORGE, outils_declares=None)
    contexte = ContexteExecution(conversation_id="c", racine_bac=Path("/tmp"))
    appel = {"name": "lire_fichier", "arguments": {"chemin": "app.py"}}

    async def jouer() -> list[str]:
        return [e["sortie"] async for e in _executer_appels([appel] * appels, messages, contexte, etat)
                if "sortie" in e]

    return asyncio.run(jouer()), etat.redites


def test_scenario_continue_le_fichier_deja_lu_n_est_pas_resservi(monkeypatch: pytest.MonkeyPatch) -> None:
    recus, redites = _rejouer(monkeypatch, FICHIER, appels=1)
    assert redites == 1 and FICHIER not in recus[0] and "already in your context" in recus[0]


def test_scenario_boucle_de_relectures_finit_en_consigne_d_arret(monkeypatch: pytest.MonkeyPatch) -> None:
    recus, redites = _rejouer(monkeypatch, FICHIER, appels=REDITES_INSISTANTES)
    assert redites == REDITES_INSISTANTES and "Stop reading" in recus[-1]


def test_scenario_fichier_modifie_entre_temps_relu_en_entier(monkeypatch: pytest.MonkeyPatch) -> None:
    modifie = FICHIER.replace("ligne 3 ", "ligne 3 corrigée ")
    recus, redites = _rejouer(monkeypatch, modifie, appels=1)
    assert redites == 0 and recus == [modifie]


def test_redite_courte_du_meme_appel_reconnue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Photo du 2026-11-10 : « [lignes 439-438 sur 438] » (24 car.) relu quinze fois."""
    recus, redites = _rejouer(monkeypatch, "[lignes 439-438 sur 438]", appels=3, historique=HISTORIQUE[:1])
    assert recus[0] == "[lignes 439-438 sur 438]" and redites == 2


def test_boucle_sans_fin_coupee_par_le_harnais() -> None:
    from backend.inference.memoire_travail import tourne_en_rond

    assert not tourne_en_rond(REDITES_ARRET - 1) and tourne_en_rond(REDITES_ARRET)


def test_une_boucle_enregistree_ne_revient_pas_au_modele() -> None:
    """Après une boucle, l'historique remontrait vingt fois la même annonce, et le modèle la recopiait."""
    bloc = "<outil><entree>lire_fichier(chemin : a.py)</entree><sortie>ok</sortie></outil>"
    boucle = "Je vais corriger l'application.\n" * 20 + f"Je lis.{bloc}Je vais corriger l'application."
    prose = " ".join(s.contenu for s in deplier(boucle) if s.role == "assistant")
    assert prose.count("Je vais corriger") == 1


def test_une_consigne_glissee_redevient_un_message_utilisateur() -> None:
    """Demandé le 2026-11-10 : un message glissé pendant le travail reste lu aux tours suivants."""
    texte = (f"Je lis.{_bloc('lire_fichier(chemin : a.py)', 'x')}\n<consigne>id:k1\nUtilise pnpm</consigne>\n"
             f"{_bloc('executer_commande(commande : ls)', 'ok')}Fini.")
    segments = deplier(texte)
    assert [s.role for s in segments] == ["assistant", "tool", "user", "assistant", "tool", "assistant"]
    assert "Utilise pnpm" in segments[2].contenu and "id:k1" not in segments[2].contenu
