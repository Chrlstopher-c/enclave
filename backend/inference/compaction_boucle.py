"""Compaction PENDANT une tâche d'agent : entre deux tours d'outils, comme Quart en fin d'étape.

`chat` compacte au départ d'un message de l'utilisateur ; mais en mode projet un seul message déclenche
des dizaines d'appels, et la boucle d'outils grossissait jusqu'à « fenêtre pleine » sans jamais
compacter (2026-10-02). Ici, après un tour d'outil, si la règle commune (`core.politique_compaction`)
le dit, les tours anciens sont remplacés PAR UN RÉSUMÉ dans la liste envoyée au moteur — la réponse
enregistrée, elle, n'est jamais touchée.

Ce qui est toujours gardé intact : le socle (messages `system` de tête), la DEMANDE en cours (dernier
message `user`), et la queue récente, coupée sur une frontière de tour d'assistant pour qu'une sortie
d'outil ne soit jamais séparée de l'appel qui l'a produite.
"""

from __future__ import annotations

import json

from collections.abc import Sequence
from dataclasses import dataclass, field

from loguru import logger

from backend.core.politique_compaction import (
    DIRECTIVES_MAX_TOKENS,
    FICHIERS_MAX_TOKENS,
    RESUME_MAX_TOKENS,
    budget_queue,
    decider,
)
from backend.inference.engines_adapters import MessageChat, superviseur
from backend.inference.fichiers_travail import selection, suivre
from backend.inference.resume_compaction import produire_resume

MARQUEUR_RESUME = "[RÉSUMÉ DU TRAVAIL DÉJÀ FAIT DANS CETTE TÂCHE — relu à la place des tours repliés]"
# Sous-estimation volontaire du ratio caractères/token : on mesure pour de vrai un peu trop tôt plutôt
# que trop tard. Le ratio réel, une fois mesuré, remplace cette valeur.
CARACTERES_PAR_TOKEN_PRUDENT = 2.5
# Une sortie d'outil n'est donnée au résumeur qu'en extrait : début et fin. Le résumé n'en garde que la
# conclusion, et 80 k tokens de sorties à relire coûteraient plusieurs minutes de traitement.
EXTRAIT_SORTIE_DEBUT = 300
EXTRAIT_SORTIE_FIN = 900
# L'estimation surévalue les tokens de 15 % : mieux vaut une mesure de trop qu'un seuil franchi sans le voir.
MARGE_ESTIMATION = 0.85
# Réglages de Chris (2026-11-10) : ses DERNIÈRES consignes restent mot pour mot dans ~2K tokens (≈ 1 500
# mots) ; au-delà elles ne vivent que condensées dans le résumé (DIRECTIVES ACTIVES), si elles valent encore.
DIRECTIVES_BRUTES_TOKENS = DIRECTIVES_MAX_TOKENS
# Matériau donné au résumeur : borné pour que SA requête tienne aussi dans la fenêtre (les plus récents gardés).
FRACTION_MATERIAU = 0.45
PREFIXE_CONSIGNE = "[Message from the user"
ENTETE_DIRECTIVES = "LATEST USER INSTRUCTIONS (verbatim, still in force unless the user said otherwise):"
ENTETE_FICHIERS = ("WORKING FILES — last known version of the files you were working on. They are up to date: "
                   "do not read them again unless you change them.")


@dataclass
class EtatCompaction:
    """Porté par la boucle : fenêtre et ratio mesurés une fois, puis réutilisés."""

    fenetre: int | None = None
    caracteres_par_token: float = CARACTERES_PAR_TOKEN_PRUDENT
    compactions: int = 0
    # La demande de l'utilisateur, repérée par IDENTITÉ : les relances du harnais sont aussi des
    # messages `user`, et « le dernier `user` » aurait gardé une consigne en repliant la vraie demande.
    demande: MessageChat | None = None
    projet: bool = False
    # Consignes de l'utilisateur gardées mot pour mot d'une compaction à la suivante (plus anciennes d'abord).
    directives: list[str] = field(default_factory=list)
    # Définitions d'outils envoyées à chaque tour (~4K tokens) : comptées dans la mesure, comme par le moteur.
    socle_outils: str = ""
    # Dernière occupation connue (mesurée, ou estimée entre deux mesures) : affichée en direct au panneau.
    occupation: int | None = None


def demarrer(messages: Sequence[MessageChat], projet: bool = False, socle_outils: str = "") -> EtatCompaction:
    """État de compaction d'une boucle : la demande est le dernier `user` AVANT le premier tour d'outil."""
    return EtatCompaction(demande=next((m for m in reversed(messages) if m.role == "user"), None), projet=projet,
                          socle_outils=socle_outils)


def _caracteres(messages: Sequence[MessageChat]) -> int:
    """Taille estimée, arguments d'appels compris : un `write_file` porte tout le fichier dans son appel."""
    return sum((len(m.content) if isinstance(m.content, str) else 2_000)
               + (len(json.dumps(m.tool_calls, ensure_ascii=False)) if m.tool_calls else 0) for m in messages)


def _tete(messages: Sequence[MessageChat]) -> int:
    """Nombre de messages `system` de tête (socle), hors résumé de compaction antérieur."""
    n = 0
    while n < len(messages) and messages[n].role == "system" and not _est_resume(messages[n]):
        n += 1
    return n


def _est_resume(message: MessageChat) -> bool:
    return message.role == "system" and isinstance(message.content, str) and message.content.startswith(MARQUEUR_RESUME)


def _debut_queue(messages: Sequence[MessageChat], budget_caracteres: int, plancher: int) -> int:
    """Index où commence la queue gardée : un message `assistant`, la plus longue qui tienne dans le budget.

    Toujours au moins le dernier tour d'assistant (et ses sorties d'outils) ; jamais avant `plancher`.
    """
    debut = len(messages)
    taille = 0
    candidat = None
    for i in range(len(messages) - 1, plancher - 1, -1):
        taille += len(messages[i].content) if isinstance(messages[i].content, str) else 2_000
        if messages[i].role == "assistant":
            if candidat is not None and taille > budget_caracteres:
                break
            candidat = i
    return candidat if candidat is not None else debut


def _extrait(message: MessageChat) -> str:
    texte = message.content if isinstance(message.content, str) else "[contenu non textuel]"
    if message.role == "tool" and len(texte) > EXTRAIT_SORTIE_DEBUT + EXTRAIT_SORTIE_FIN:
        texte = f"{texte[:EXTRAIT_SORTIE_DEBUT]}\n[…]\n{texte[-EXTRAIT_SORTIE_FIN:]}"
    return f"[{message.role}]\n{texte}"


async def _mesurer(messages: Sequence[MessageChat], etat: EtatCompaction) -> int | None:
    try:
        occupation = await superviseur.compter_contexte(etat.socle_outils, list(messages))
    except Exception as exc:  # noqa: BLE001 — une mesure absente ne doit jamais casser la tâche
        logger.warning("Occupation non mesurable dans la boucle ({}) : pas de compaction.", exc)
        return None
    if not occupation.mesurable or occupation.tokens_mesures is None or not occupation.contexte_total:
        return None
    etat.fenetre = occupation.contexte_total
    if occupation.tokens_mesures:
        etat.caracteres_par_token = max(1.0, (_caracteres(messages) + len(etat.socle_outils))
                                        / occupation.tokens_mesures)
    etat.occupation = occupation.tokens_mesures
    logger.info("Occupation mesurée dans la boucle : {} / {} tokens.", occupation.tokens_mesures, etat.fenetre)
    return occupation.tokens_mesures


def _estimation_sous_seuil(messages: Sequence[MessageChat], etat: EtatCompaction, etape: bool) -> bool:
    """Le contexte est-il SÛREMENT sous le seuil ? Évite une tokenisation complète à chaque tour."""
    if etat.fenetre is None:
        return False
    estime = int((_caracteres(messages) + len(etat.socle_outils)) / (etat.caracteres_par_token * MARGE_ESTIMATION))
    etat.occupation = int(estime * MARGE_ESTIMATION)
    return decider(estime, etat.fenetre, etape) is None


async def compacter_si_besoin(messages: list[MessageChat], etat: EtatCompaction, etape_terminee: bool,
                              taches: str = "", forcer: bool = False) -> str | None:
    """Compacte `messages` SUR PLACE si la règle le demande (ou `forcer`). Rend une note, ou `None`."""
    if not forcer and _estimation_sous_seuil(messages, etat, etape_terminee):
        return None
    tokens = await _mesurer(messages, etat)
    if tokens is None or etat.fenetre is None:
        return None
    if not forcer and decider(tokens, etat.fenetre, etape_terminee) is None:
        return None
    note = await _compacter(messages, etat, tokens, taches)
    if note is not None:
        etat.compactions += 1
    return note


def _directives(replies: Sequence[MessageChat], demande_index: int | None, messages: Sequence[MessageChat],
                etat: EtatCompaction) -> list[str]:
    """Consignes de l'utilisateur à garder mot pour mot : les plus récentes, dans ~2K tokens.

    Sont des consignes : ses messages d'AVANT la demande en cours, et ceux glissés pendant le travail.
    Les relances du harnais, rôle `user` elles aussi, n'en sont pas.
    """
    limite = messages[demande_index] if demande_index is not None else None
    avant = True
    nouvelles: list[str] = []
    for message in messages:
        if message is limite:
            avant = False
        if message in replies and message.role == "user" and isinstance(message.content, str):
            if avant or message.content.startswith(PREFIXE_CONSIGNE):
                nouvelles.append(message.content.split("]\n\n", 1)[-1].strip())
    budget = int(DIRECTIVES_BRUTES_TOKENS * etat.caracteres_par_token)
    gardees: list[str] = []
    for texte in reversed([*etat.directives, *nouvelles]):
        if len(texte) > budget:
            break
        gardees.insert(0, texte)
        budget -= len(texte)
    return gardees


def _materiau(replies: Sequence[MessageChat], etat: EtatCompaction) -> str:
    """Extraits à résumer, bornés pour que la requête du résumeur tienne : les plus récents sont gardés."""
    assert etat.fenetre is not None
    budget = int(FRACTION_MATERIAU * etat.fenetre * etat.caracteres_par_token)
    extraits: list[str] = []
    for message in reversed(replies):
        extrait = _extrait(message)
        if len(extrait) > budget:
            break
        extraits.insert(0, extrait)
        budget -= len(extrait)
    return "\n\n".join(extraits)


def _corps(resume: str, taches: str, directives: list[str], fichiers: str) -> str:
    corps = f"{MARQUEUR_RESUME}\n{resume}"
    if taches:
        corps += f"\n\nListe de tâches actuelle :\n{taches}"
    if directives:
        corps += f"\n\n{ENTETE_DIRECTIVES}\n" + "\n".join(f"- {d}" for d in directives)
    if fichiers:
        corps += f"\n\n{ENTETE_FICHIERS}\n{fichiers}"
    return corps


def _precedent(messages: Sequence[MessageChat]) -> str:
    """Le résumé antérieur seul : ses blocs de consignes et de fichiers sont reconstruits à part."""
    texte = next((str(m.content) for m in messages if _est_resume(m)), "")
    texte = texte[len(MARQUEUR_RESUME):].strip() if texte else ""
    for entete in (ENTETE_DIRECTIVES, ENTETE_FICHIERS):
        texte = texte.split(f"\n\n{entete}", 1)[0]
    return texte


def _fichiers(messages: list[MessageChat], tete: int, debut: int, etat: EtatCompaction) -> str:
    """Dernière version connue des fichiers touchés dans la partie repliée, hors ceux que la queue montre déjà."""
    assert etat.fenetre is not None
    queue = messages[debut:]
    deja = set(suivre(queue))
    connus = {chemin: f for chemin, f in suivre(messages[tete:debut]).items() if chemin not in deja}
    recents = " ".join(str(m.content) for m in queue if isinstance(m.content, str))[-20_000:]
    budget = int(FICHIERS_MAX_TOKENS * etat.caracteres_par_token)
    return "\n\n".join(f.rendu() for f in selection(connus, budget, recents))


async def _compacter(messages: list[MessageChat], etat: EtatCompaction, avant: int, taches: str) -> str | None:
    assert etat.fenetre is not None
    tete = _tete(messages)
    demande = next((i for i, m in enumerate(messages) if m is etat.demande), None)
    plancher = (demande + 1) if demande is not None else tete
    budget = int(budget_queue(etat.fenetre) * etat.caracteres_par_token)
    debut = _debut_queue(messages, budget, plancher)
    replies = [m for i, m in enumerate(messages[tete:debut], start=tete) if i != demande and not _est_resume(m)]
    if not replies:
        logger.info("Compaction de boucle : rien à replier sous la queue minimale.")
        return None
    plafond = RESUME_MAX_TOKENS
    resume = await produire_resume(_materiau(replies, etat), _precedent(messages[tete:debut]), "", plafond,
                                   projet=etat.projet)
    if resume is None:
        logger.warning("Résumé de boucle indisponible : la tâche continue sur le contexte courant.")
        return None
    etat.directives = _directives(replies, demande, messages, etat)
    corps = _corps(resume, taches, etat.directives, _fichiers(messages, tete, debut, etat))
    garde_demande = [messages[demande]] if demande is not None and demande < debut else []
    messages[:] = [*messages[:tete], MessageChat(role="system", content=corps), *garde_demande, *messages[debut:]]
    logger.info("Compaction de boucle : {} messages repliés, ~{} tokens avant.", len(replies), avant)
    return f"\n\n*[Contexte compacté : {len(replies)} messages résumés ({avant} tokens avant).]*\n\n"


__all__ = ["EtatCompaction", "MARQUEUR_RESUME", "compacter_si_besoin", "demarrer"]
