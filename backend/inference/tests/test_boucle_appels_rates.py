"""Preuve que la boucle d'outils ne s'auto-alimente plus, et ne laisse plus annoncer un faux résultat.

Trois défauts distincts, tous relevés sur la même conversation réelle du 2026-08-16 (messages 141,
143 et 145 en base), tous enchaînés à partir d'un unique appel raté :

1. le balisage d'appel du modèle repartait AU MOTEUR dans son propre texte d'assistant. Un
   `<function=ecrire_fichier></function>` vide devenait donc un exemple de ce qu'il avait « fait »,
   et il le rejouait à l'identique — y compris au PREMIER tour du message suivant, où plus rien ne
   l'y poussait. Un appel raté qu'on remontre est un gabarit qu'on propose ;
2. rien n'empêchait de réexécuter exactement le même appel : trois tours, trois fois le même échec ;
3. la clôture ignorait que rien n'avait abouti. Le modèle a terminé sur « Voici le nouveau fichier
   […] vous pouvez l'ouvrir en cliquant sur la carte ci-dessus » alors qu'aucun fichier n'existait
   et qu'aucune carte n'était affichée. C'est le pire des trois : l'utilisateur ne pouvait même pas
   savoir que l'opération avait échoué.

Ces tests matérialisent les MÉCANISMES, pas le symptôme : un vrai modèle est non déterministe, et
une reproduction en conditions réelles ne ferait pas un test de régression fiable.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import backend.inference as domaine_inference
from backend.chat.modeles import ParametresEchantillonnage
from backend.chat.port_inference import MessageInference, RequeteGeneration
from backend.inference import (
    _AUCUN_OUTIL_ABOUTI,
    _REDITE,
    MoteurChat,
    _messages_depuis,
    _sans_appels_outils,
)
from backend.inference.engines_adapters.contrat import MessageChat, MorceauGeneration, OptionsGeneration
from backend.outils import registre
from backend.outils.contrat import ContexteExecution, DescriptionOutil, EchecOutil, Outil

CONVERSATION = "conversation-appels-rates"
APPEL_VIDE = "<function=ecrire_fichier>\n</function>"


class _MessageFactice:
    def __init__(self, role: str, contenu: str) -> None:
        self.role = role
        self.contenu = contenu


# --- retrait du balisage d'appel dans ce qui repart au moteur -----------------------------------


def test_un_appel_balise_est_retire_du_texte_qui_repart() -> None:
    assert _sans_appels_outils(f"Je crée le fichier.{APPEL_VIDE}") == "Je crée le fichier."


def test_un_appel_json_est_retire_lui_aussi() -> None:
    texte = 'Je cherche.<tool_call>{"name": "recherche_web", "arguments": {}}</tool_call>'
    assert _sans_appels_outils(texte) == "Je cherche."


def test_un_appel_non_ferme_est_retire_jusqu_a_la_fin() -> None:
    """Une génération arrêtée net laisse une balise ouverte — la garder la rendrait imitable."""
    assert _sans_appels_outils("Bon.<function=ecrire_fichier><parameter=chemin>a.py") == "Bon."


def test_le_raisonnement_et_la_prose_traversent_intacts() -> None:
    """Le modèle doit garder le fil de ce qu'il faisait : seule la FORME de l'appel disparaît."""
    texte = f"Je vais écrire la page.{APPEL_VIDE}Ensuite je la présenterai."
    assert _sans_appels_outils(texte) == "Je vais écrire la page.Ensuite je la présenterai."


def test_un_texte_sans_appel_n_est_pas_touche() -> None:
    texte = "Une réponse ordinaire, avec un < et un > au passage."
    assert _sans_appels_outils(texte) == texte


def test_l_historique_arrive_au_moteur_sans_appel_a_recopier() -> None:
    """Le point d'entrée réel : c'est `_messages_depuis` qui relit les messages enregistrés."""
    convertis = _messages_depuis([_MessageFactice("assistant", f"J'écris.{APPEL_VIDE}")])

    assert "<function=" not in str(convertis[0].content)
    assert "J'écris." in str(convertis[0].content)


# --- boucle : redite bornée, clôture honnête ----------------------------------------------------


class _SuperviseurInsistant:
    """Redemande TOUJOURS le même appel, comme le modèle observé le 2026-08-16.

    Retient les messages du dernier appel reçu : c'est ainsi qu'on vérifie ce que le tour de
    clôture a réellement sous les yeux.
    """

    def __init__(self) -> None:
        self.tours = 0
        self.derniers_messages: list[MessageChat] = []

    def generer(
        self,
        messages: Sequence[MessageChat],
        options: OptionsGeneration,
        outils: Sequence[dict[str, Any]] | None = None,
    ) -> AsyncIterator[MorceauGeneration]:
        self.tours += 1
        self.derniers_messages = list(messages)
        return self._flux(demande_outil=outils is not None or self.tours <= 3)

    async def _flux(self, *, demande_outil: bool) -> AsyncIterator[MorceauGeneration]:
        if demande_outil:
            yield MorceauGeneration(type="token", contenu=f"Je m'en occupe.{APPEL_VIDE}")
        else:
            yield MorceauGeneration(type="token", contenu="Voici le fichier, ouvrez la carte.")


def _outil_toujours_en_echec(executions: list[dict[str, Any]]) -> Outil:
    async def executer(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
        executions.append(arguments)
        raise EchecOutil("Failed: `ecrire_fichier` was called without everything it needs.")

    return Outil(
        description=DescriptionOutil(
            nom="ecrire_fichier",
            description="Outil de test, en échec par construction.",
            parametres={"type": "object", "properties": {}},
        ),
        executer=executer,
    )


def _jouer(monkeypatch: Any) -> tuple[_SuperviseurInsistant, list[dict[str, Any]], str]:
    """Fait tourner un tour complet et rend le superviseur, les exécutions et le texte diffusé."""
    executions: list[dict[str, Any]] = []
    monkeypatch.setitem(registre._OUTILS, "ecrire_fichier", _outil_toujours_en_echec(executions))
    superviseur = _SuperviseurInsistant()
    monkeypatch.setattr(domaine_inference, "superviseur", superviseur)

    async def lire() -> str:
        morceaux: list[str] = []
        async for morceau in MoteurChat().generer(
            RequeteGeneration(
                messages=[MessageInference(role="user", contenu="refais la page")],
                parametres=ParametresEchantillonnage(),
                conversation_id=CONVERSATION,
            )
        ):
            texte = morceau.get("texte")
            if isinstance(texte, str):
                morceaux.append(texte)
        return "".join(morceaux)

    return superviseur, executions, asyncio.run(lire())


def test_le_meme_appel_n_est_execute_qu_une_fois(monkeypatch: Any) -> None:
    """Trois tours demandaient le même appel : réexécuter donnait trois fois le même échec."""
    _, executions, diffuse = _jouer(monkeypatch)

    assert len(executions) == 1, "les redites ne sont pas rejouées"
    assert _REDITE.split("{cause}")[0] in diffuse, "la redite est dite au modèle, pas avalée en silence"
    assert diffuse.count("NOT RUN") >= 1 and "Its failure was:\n" in diffuse, "la cause de l'échec est redite"


def test_la_cloture_sait_qu_aucun_outil_n_a_abouti(monkeypatch: Any) -> None:
    """Sans ce rappel, le modèle annonçait un fichier et une carte qui n'existaient pas."""
    superviseur, _, _ = _jouer(monkeypatch)

    consignes = [m for m in superviseur.derniers_messages if str(m.content) == _AUCUN_OUTIL_ABOUTI]
    assert consignes, "la consigne de clôture est injectée quand rien n'a abouti"
    assert consignes[0].role == "tool", "elle passe par le canal des résultats, pas par la prose"


def test_la_cloture_ne_remontre_pas_l_appel_rate(monkeypatch: Any) -> None:
    """La cause première : le modèle recopiait le `<function=…>` vide qu'on lui remettait sous les yeux."""
    superviseur, _, _ = _jouer(monkeypatch)

    assert not any("<function=" in str(m.content) for m in superviseur.derniers_messages)


def test_une_reponse_est_toujours_produite(monkeypatch: Any) -> None:
    """La borne atteinte ne doit jamais laisser la conversation sans un mot."""
    _, _, diffuse = _jouer(monkeypatch)

    assert "Voici le fichier" in diffuse
