"""Preuve de la logique de compaction — seuil, point de coupe, résumé cumulatif — SANS DB ni moteur.

Le franchissement réel du seuil sur un vrai modèle est prouvé ailleurs (intégration, petit contexte).
Ici on isole la DÉCISION : un faux moteur au comptage déterministe (un token par caractère) rend la
mesure prévisible, la coupe vérifiable, et le caractère cumulatif du résumé opposable. Aucun accès
disque, aucun réseau — c'est ce qui rend ces règles vérifiables tour après tour.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from backend.chat import compaction
from backend.chat.compaction import (
    GARDER_MINIMUM,
    MessageAncre,
    appliquer,
    choisir_nb_gardes,
    depasse_seuil,
    preparer_compaction,
)
from backend.chat.modeles import InfoCompaction
from backend.chat.port_inference import MessageInference, OccupationContexte

CONTEXTE = 100


def _ancre(identifiant: str, taille: int) -> MessageAncre:
    """Un message d'historique de `taille` caractères — donc `taille` tokens pour le faux moteur."""
    return MessageAncre(id=identifiant, message=MessageInference(role="user", contenu="m" * taille))


def _occupation(tokens: int) -> OccupationContexte:
    return OccupationContexte(
        mesurable=True, contexte_total=CONTEXTE, tokens_mesures=tokens, tokens_libres=CONTEXTE - tokens
    )


class _FauxMoteur:
    """Compte un token par caractère de `contenu`, et résume en une chaîne courte traçable.

    Déterministe et monotone : l'occupation d'une liste croît avec elle, ce qui rend la dichotomie du
    point de coupe vérifiable. Chaque résumé retient le résumé antérieur qu'on lui a passé — c'est
    ainsi qu'on prouve que la compaction est cumulative et n'oublie pas.
    """

    def __init__(self) -> None:
        self.resumes_demandes: list[tuple[str, str]] = []
        self.compteur = 0

    async def mesurer_occupation(self, messages: Sequence[MessageInference]) -> OccupationContexte:
        return _occupation(sum(len(m.contenu) for m in messages))

    async def resumer(self, a_resumer: str, resume_precedent: str, langue: str, max_tokens: int) -> str | None:
        self.resumes_demandes.append((a_resumer, resume_precedent))
        self.compteur += 1
        return f"R{self.compteur}"  # court : le résumé pèse moins que les messages repliés


def test_depasse_seuil_franchi_au_seuil_d_etape() -> None:
    """Fenêtre de 100 : seuil d'étape = 40 % (règle de Quart), plafond 120 k sans effet ici."""
    assert depasse_seuil(_occupation(40)) is True
    assert depasse_seuil(_occupation(41)) is True
    assert depasse_seuil(_occupation(39)) is False


def test_une_mesure_absente_ne_declenche_jamais() -> None:
    assert depasse_seuil(OccupationContexte(mesurable=False)) is False
    assert depasse_seuil(OccupationContexte(mesurable=True, contexte_total=None, tokens_mesures=None)) is False


def test_choisir_garde_la_plus_longue_queue_sous_le_budget() -> None:
    # queue de k messages de 10 tokens + socle 10 : 10 + 10k <= 50  ⇒  k <= 4
    async def mesurer_tail(k: int) -> int | None:
        return 10 + 10 * k

    nb = asyncio.run(choisir_nb_gardes(10, mesurer_tail, budget_tokens=50))
    assert nb == 4


def test_choisir_plancher_au_minimum_quand_la_mesure_manque() -> None:
    async def mesurer_tail(_k: int) -> int | None:
        return None

    nb = asyncio.run(choisir_nb_gardes(10, mesurer_tail, budget_tokens=50))
    assert nb == GARDER_MINIMUM


def test_appliquer_sans_compaction_rend_socle_puis_tout_l_historique() -> None:
    ancres = [_ancre("a", 10), _ancre("b", 10)]
    messages = appliquer("SOCLE", ancres, None)
    assert [m.role for m in messages] == ["system", "user", "user"]
    assert messages[0].contenu == "SOCLE"


def test_appliquer_une_compaction_active_remplace_les_tours_d_avant_la_coupe() -> None:
    ancres = [_ancre("a", 10), _ancre("b", 10), _ancre("c", 10), _ancre("d", 10)]
    active = _info(coupe="b", resume="RESUME", nb=2)
    messages = appliquer("SOCLE", ancres, active)
    # socle + résumé + (c, d) : a et b sont repliés dans le résumé.
    assert len(messages) == 4
    assert messages[0].contenu == "SOCLE"
    assert "RESUME" in messages[1].contenu and messages[1].role == "system"
    assert [m.contenu for m in messages[2:]] == ["m" * 10, "m" * 10]


def test_une_compaction_hors_chemin_est_ignoree() -> None:
    ancres = [_ancre("a", 10), _ancre("b", 10)]
    active = _info(coupe="inconnu", resume="RESUME", nb=1)
    messages = appliquer("SOCLE", ancres, active)
    # La coupe ne tombe sur aucun message du chemin : on rend tout l'historique, sans résumé.
    assert [m.contenu for m in messages] == ["SOCLE", "m" * 10, "m" * 10]


def test_sous_le_seuil_aucune_compaction() -> None:
    moteur = _FauxMoteur()
    ancres = [_ancre(f"m{i}", 5) for i in range(5)]  # 25 + socle 10 = 35 < 90
    resultat = asyncio.run(
        preparer_compaction(moteur, "S" * 10, ancres, None, conversation_id="c", message_id="x")
    )
    assert resultat.info is None
    assert moteur.resumes_demandes == []
    assert [m.contenu for m in resultat.messages][1:] == ["m" * 5] * 5


def test_au_dessus_du_seuil_compaction_declenchee_et_chiffree() -> None:
    moteur = _FauxMoteur()
    ancres = [_ancre(f"m{i}", 20) for i in range(10)]  # 200 + socle 10 = 210 > 90
    resultat = asyncio.run(
        preparer_compaction(moteur, "S" * 10, ancres, None, conversation_id="c", message_id="x")
    )
    info = resultat.info
    assert info is not None
    # queue de 2 (le plancher) tenue sous 50 tokens ⇒ 8 messages repliés, coupe sur le 8ᵉ (index 7).
    assert info.nb_messages_resumes == 8
    assert info.coupe_message_id == "m7"
    assert info.tokens_avant == 210
    assert info.tokens_apres < info.tokens_avant
    assert info.contexte_total == CONTEXTE
    # Ce qui part au moteur : socle + résumé + les 2 derniers messages intacts.
    assert resultat.messages[0].contenu == "S" * 10
    assert info.resume in resultat.messages[1].contenu
    assert [m.contenu for m in resultat.messages[2:]] == ["m" * 20] * 2


def test_le_resume_est_cumulatif_il_englobe_le_precedent() -> None:
    moteur = _FauxMoteur()
    ancres = [_ancre(f"m{i}", 20) for i in range(10)]
    premier = asyncio.run(
        preparer_compaction(moteur, "S" * 10, ancres, None, conversation_id="c", message_id="x1")
    ).info
    assert premier is not None

    # La conversation s'allonge : on repasse au-dessus du seuil, la compaction précédente est active.
    suite = ancres + [_ancre(f"n{i}", 20) for i in range(6)]
    second = asyncio.run(
        preparer_compaction(moteur, "S" * 10, suite, premier, conversation_id="c", message_id="x2")
    ).info
    assert second is not None
    # Le second résumé a reçu le premier À ENGLOBER — la preuve qu'il ne l'oublie pas.
    _, resume_precedent_transmis = moteur.resumes_demandes[-1]
    assert resume_precedent_transmis == premier.resume
    # Le compte cumulé dépasse celui de la première compaction : il ajoute les nouveaux tours repliés.
    assert second.nb_messages_resumes > premier.nb_messages_resumes
    assert second.coupe_message_id != premier.coupe_message_id


def _info(*, coupe: str, resume: str, nb: int) -> InfoCompaction:
    return InfoCompaction(
        id="i",
        conversation_id="c",
        message_id="msg",
        coupe_message_id=coupe,
        nb_messages_resumes=nb,
        tokens_avant=110,
        tokens_apres=50,
        contexte_total=CONTEXTE,
        resume=resume,
        cree_le="2026-08-28T00:00:00+00:00",
    )
