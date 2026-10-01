"""Preuve que les outils ne sont plus repassés au moteur après un tour ayant produit des résultats
(plan d'exécution, L10-b).

Défaut réel, observé il y a moins d'une heure : un modèle à qui on montrait une image a bouclé
trois fois sur l'outil de présentation au lieu de répondre. Cause identifiée : `outils` était
calculé une fois hors de la boucle de tours, puis repassé à `superviseur.generer` À CHAQUE tour, y
compris après qu'un tour a déjà exécuté un outil et reçu son résultat — le modèle voit donc
toujours les mêmes outils sous les yeux et n'a aucune raison d'arrêter d'en redemander.

Un vrai modèle est non déterministe : il ne boucle pas à tous les coups sur le même prompt, ce qui
rend une reproduction en conditions réelles peu fiable comme test de RÉGRESSION (elle reste dans
le rapport de mission, comme preuve ponctuelle). Ce test-ci matérialise le MÉCANISME plutôt que le
symptôme : `SuperviseurBoucleFactice` redemande l'outil **si et seulement si** on lui repasse des
outils non vides — exactement le déclencheur du bug. C'est `MoteurChat._flux` (le vrai) qui décide
quoi lui repasser à chaque tour, via `backend.outils.registre` (le vrai) pour l'exécution.
"""

from __future__ import annotations

import pytest

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

CONVERSATION_ATTENDUE = "conversation-boucle-42"

@pytest.fixture(autouse=True)
def _harnais_d_origine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ces cas décrivent la conduite d'origine (6 tours puis couperet, sans relance) : ils la figent,
    le défaut étant passé à FORGE (prolongations illimitées, relance des tours muets)."""
    from backend.inference import harnais

    monkeypatch.setattr(harnais, "DEFAUT", harnais.ECHOHUB)



class SuperviseurBoucleFactice:
    """Redemande l'outil tant qu'on le lui présente — jamais autrement.

    Ce n'est pas « le modèle qui boucle » : c'est le harnais qui continue de lui montrer l'outil.
    Le simulateur rend cette dépendance explicite et vérifiable : sa seule variable d'entrée est
    `outils`, exactement celle que `MoteurChat._flux` doit cesser de repasser après un tour avec
    résultats.
    """

    def __init__(self) -> None:
        self.tours = 0
        self.outils_recus: list[bool] = []

    def generer(
        self,
        messages: Sequence[MessageChat],
        options: OptionsGeneration,
        outils: Sequence[dict[str, Any]] | None = None,
    ) -> AsyncIterator[MorceauGeneration]:
        self.tours += 1
        presents = bool(outils)
        self.outils_recus.append(presents)
        return self._flux(demande_outil=presents)

    async def _flux(self, *, demande_outil: bool) -> AsyncIterator[MorceauGeneration]:
        if demande_outil:
            yield MorceauGeneration(
                type="token",
                contenu='<tool_call>{"name": "outil_factice", "arguments": {}}</tool_call>',
            )
        else:
            yield MorceauGeneration(type="token", contenu="Réponse finale, sans nouvel outil.")


def _requete_test() -> RequeteGeneration:
    return RequeteGeneration(
        messages=[MessageInference(role="user", contenu="montre-moi le résultat")],
        parametres=ParametresEchantillonnage(),
        conversation_id=CONVERSATION_ATTENDUE,
    )


def _consommer(requete: RequeteGeneration) -> None:
    async def lire() -> None:
        moteur = MoteurChat()
        async for _ in moteur.generer(requete):
            pass

    asyncio.run(lire())


class SuperviseurInsistantFactice:
    """Demande un outil aux DEUX premiers tours, qu'on lui en présente ou non.

    C'est le comportement réel d'un modèle qui enchaîne « j'exécute le code » puis « je présente le
    fichier produit » : le second appel arrive à un tour où le harnais ne déclare plus les outils.
    """

    def __init__(self) -> None:
        self.tours = 0
        self.outils_recus: list[bool] = []

    def generer(
        self,
        messages: Sequence[MessageChat],
        options: OptionsGeneration,
        outils: Sequence[dict[str, Any]] | None = None,
    ) -> AsyncIterator[MorceauGeneration]:
        self.tours += 1
        self.outils_recus.append(bool(outils))
        return self._flux(demande_outil=self.tours <= 2)

    async def _flux(self, *, demande_outil: bool) -> AsyncIterator[MorceauGeneration]:
        if demande_outil:
            yield MorceauGeneration(
                type="token",
                contenu='<tool_call>{"name": "outil_factice", "arguments": {}}</tool_call>',
            )
        else:
            yield MorceauGeneration(type="token", contenu="Voici le résultat.")


def test_un_appel_demande_au_second_tour_est_execute(monkeypatch: Any) -> None:
    """Régression du 2026-08-16 : l'appel du second tour était détecté puis JAMAIS exécuté.

    La condition de sortie portait à la fois sur les appels demandés et sur les outils encore
    déclarés. Ces derniers valant `None` dès le second tour (L10-b), la boucle sortait sans
    exécuter, et le `<tool_call>` restait affiché en XML brut dans la réponse — c'est ce que
    l'utilisateur a vu quand `presenter_fichier` « ne marchait pas ». Cesser de DÉCLARER un outil
    ne doit pas revenir à refuser de faire ce que le modèle demande ; seul `TOURS_OUTILS_MAX` borne.
    """
    executions: list[int] = []

    async def executer_outil_factice(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
        executions.append(1)
        return "fait"

    outil_factice = Outil(
        description=DescriptionOutil(
            nom="outil_factice",
            description="Outil de test, sans effet réel.",
            parametres={"type": "object", "properties": {}},
        ),
        executer=executer_outil_factice,
    )
    monkeypatch.setitem(registre._OUTILS, outil_factice.nom, outil_factice)
    superviseur_factice = SuperviseurInsistantFactice()
    monkeypatch.setattr(domaine_inference, "superviseur", superviseur_factice)

    _consommer(_requete_test())

    assert len(executions) == 2, "les DEUX appels demandés sont exécutés, y compris celui du second tour"
    assert superviseur_factice.outils_recus[:2] == [True, True], (
        "le modèle voit ses outils aux deux tours : c'est ce qui lui permet d'enchaîner "
        "`executer_python` puis `presenter_fichier` (L10-b abandonné le 2026-08-16, sur mesure)"
    )


class SuperviseurEspionFactice:
    """Demande un outil au premier tour, puis retient les messages reçus au tour suivant."""

    def __init__(self) -> None:
        self.tours = 0
        self.messages_du_second_tour: list[MessageChat] = []

    def generer(
        self,
        messages: Sequence[MessageChat],
        options: OptionsGeneration,
        outils: Sequence[dict[str, Any]] | None = None,
    ) -> AsyncIterator[MorceauGeneration]:
        self.tours += 1
        if self.tours == 2:
            self.messages_du_second_tour = list(messages)
        return self._flux(demande_outil=self.tours == 1)

    async def _flux(self, *, demande_outil: bool) -> AsyncIterator[MorceauGeneration]:
        if demande_outil:
            yield MorceauGeneration(
                type="token",
                contenu='<tool_call>{"name": "outil_factice", "arguments": {}}</tool_call>',
            )
        else:
            yield MorceauGeneration(type="token", contenu="Voici le résultat.")


def test_le_resultat_repart_avec_le_role_tool_et_sans_prefixe(monkeypatch: Any) -> None:
    """Régression du 2026-08-16 : le modèle imitait le format d'injection au lieu d'appeler l'outil.

    Les résultats repartaient en rôle `assistant`, préfixés « [outil nom — résultat] ». Le modèle a
    fini par écrire ce préfixe lui-même, en prose — « [outil presenter_fichier] Affichant le
    fichier … » — et aucune carte n'apparaissait, puisqu'aucun outil n'avait été appelé. Le rôle
    `tool` est le canal natif du gabarit, que le modèle ne confond pas avec sa propre écriture.
    """

    async def executer_outil_factice(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
        return "SORTIE BRUTE DE L'OUTIL"

    outil_factice = Outil(
        description=DescriptionOutil(
            nom="outil_factice",
            description="Outil de test, sans effet réel.",
            parametres={"type": "object", "properties": {}},
        ),
        executer=executer_outil_factice,
    )
    monkeypatch.setitem(registre._OUTILS, outil_factice.nom, outil_factice)
    espion = SuperviseurEspionFactice()
    monkeypatch.setattr(domaine_inference, "superviseur", espion)

    _consommer(_requete_test())

    resultats = [m for m in espion.messages_du_second_tour if m.role == "tool"]
    assert len(resultats) == 1, "le résultat d'outil repart avec le rôle `tool`"
    assert resultats[0].content == "SORTIE BRUTE DE L'OUTIL", "contenu nu : le gabarit l'enveloppe lui-même"
    assert all(
        "[outil" not in str(m.content) for m in espion.messages_du_second_tour
    ), "aucun préfixe inventé dans l'historique : c'est ce que le modèle imitait"


class SuperviseurEntetantFactice:
    """Demande un outil à CHAQUE tour, sans jamais répondre — sauf si on ne lui déclare rien.

    Reproduit le modèle observé le 2026-08-16 : il réémettait un appel vide, recevait « aucun code
    fourni », s'en excusait, et recommençait jusqu'à épuisement de la borne.
    """

    def __init__(self) -> None:
        self.tours = 0
        self.outils_recus: list[bool] = []

    def generer(
        self,
        messages: Sequence[MessageChat],
        options: OptionsGeneration,
        outils: Sequence[dict[str, Any]] | None = None,
    ) -> AsyncIterator[MorceauGeneration]:
        self.tours += 1
        self.outils_recus.append(bool(outils))
        return self._flux()

    async def _flux(self) -> AsyncIterator[MorceauGeneration]:
        yield MorceauGeneration(
            type="token",
            contenu='<tool_call>{"name": "outil_factice", "arguments": {}}</tool_call>',
        )


def test_la_borne_atteinte_produit_quand_meme_une_reponse(monkeypatch: Any) -> None:
    """Régression du 2026-08-16 : la borne épuisée laissait la conversation SANS un mot.

    Les trois tours demandaient tous un outil, donc aucun n'écrivait de réponse, et la boucle
    rendait la main — l'interface affichait « le modèle n'a rien écrit en dehors de son
    raisonnement » sous une pile de blocs d'outils. Un tour de clôture, sans outil déclaré, doit
    suivre la borne.
    """
    executions: list[int] = []

    async def executer_outil_factice(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
        executions.append(1)
        return "fait"

    outil_factice = Outil(
        description=DescriptionOutil(
            nom="outil_factice",
            description="Outil de test, sans effet réel.",
            parametres={"type": "object", "properties": {}},
        ),
        executer=executer_outil_factice,
    )
    monkeypatch.setitem(registre._OUTILS, outil_factice.nom, outil_factice)
    superviseur_factice = SuperviseurEntetantFactice()
    monkeypatch.setattr(domaine_inference, "superviseur", superviseur_factice)

    _consommer(_requete_test())

    assert len(executions) == domaine_inference.TOURS_OUTILS_MAX, "la borne limite bien les exécutions"
    assert superviseur_factice.tours == domaine_inference.TOURS_OUTILS_MAX + 1, (
        "un tour de clôture suit la borne, pour qu'une réponse existe malgré tout"
    )
    assert superviseur_factice.outils_recus[-1] is False, (
        "le tour de clôture ne déclare aucun outil : c'est une clôture, pas une chance de plus"
    )


def test_les_outils_restent_declares_a_chaque_tour(monkeypatch: Any) -> None:
    """Renversement du 2026-08-16, imposé par la mesure — L10-b est abandonné.

    Les outils n'étaient déclarés qu'au PREMIER tour, pour empêcher un modèle de redemander sans
    fin un outil dont il avait déjà le résultat. Mesuré en conditions réelles sur le MoE 35B,
    contexte servi de 131 072 tokens dont 18 835 occupés — donc sans la moindre contrainte de
    fenêtre : le modèle appelle `lire_fichier`, apprend que le fichier n'existe pas, annonce « je
    repars de zéro, voici la nouvelle version »… et s'arrête. Il n'avait pas renoncé :
    `ecrire_fichier` ne lui était simplement plus déclaré. C'est le symptôme rapporté par
    l'utilisateur — « ça coupe alors que le contexte est large ».

    La boucle de travail que le socle DEMANDE compte plusieurs appels enchaînés (écrire, exécuter,
    relire, corriger, présenter). Lui retirer ses outils au deuxième tour n'était pas une
    protection, c'était une amputation. Ce que L10-b protégeait est désormais couvert et mieux
    ciblé : `TOURS_OUTILS_MAX`, l'anti-redite sur les appels échoués, et le retrait du balisage
    d'appel de l'historique renvoyé. Le test suivant prouve que la borne tient toujours.
    """
    executions: list[int] = []

    async def executer_outil_factice(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
        executions.append(1)
        return "fait"

    outil_factice = Outil(
        description=DescriptionOutil(
            nom="outil_factice",
            description="Outil de test, sans effet réel.",
            parametres={"type": "object", "properties": {}},
        ),
        executer=executer_outil_factice,
    )
    monkeypatch.setitem(registre._OUTILS, outil_factice.nom, outil_factice)
    superviseur_factice = SuperviseurBoucleFactice()
    monkeypatch.setattr(domaine_inference, "superviseur", superviseur_factice)

    _consommer(_requete_test())

    tours_avec_outils = superviseur_factice.outils_recus[: domaine_inference.TOURS_OUTILS_MAX]
    assert all(tours_avec_outils), "un modèle qui enchaîne deux outils doit les voir aux deux tours"
    assert superviseur_factice.outils_recus[-1] is False, (
        "seul le tour de CLÔTURE se fait sans outil : c'est ce qui garantit une réponse"
    )
    # La borne remplace L10-b : un modèle qui redemande l'outil dès qu'on le lui montre boucle
    # jusqu'à `TOURS_OUTILS_MAX`, puis la clôture rend la main. Il ne boucle pas indéfiniment.
    assert len(executions) == domaine_inference.TOURS_OUTILS_MAX
