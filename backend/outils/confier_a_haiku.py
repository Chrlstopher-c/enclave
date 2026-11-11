"""Outil `confier_a_haiku` — mode hybride : l'agent local pilote, Claude Haiku écrit le code, À L'AVEUGLE.

Mesuré le 2026-11-11 (« Tetris test 35B + Haiku 2 ») : avec `deleguer_code`, le 35B recopiait lui-même le code
rendu par Haiku — ~25 000 caractères retapés à ~21 tokens/s. Ici Haiku écrit les fichiers lui-même, et le
HARNAIS les pose dans le projet : l'agent local ne retape rien.

Confidentialité (exigence de Chris) : Haiku ne voit JAMAIS le projet. Il travaille dans un espace vierge du relais
(`docker/resumeur-hote`, abonnement Claude Code, jamais l'API), identifié par une empreinte opaque. Il n'y trouve
que la tâche et les fichiers qu'il a lui-même produits auparavant (leur état courant). Tout ce qui part — tâche
et fichiers — passe la garde `code_aveugle.fuites_texte` (nom du projet, canaris, URL, chemins, IP, secrets).
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

import httpx
from loguru import logger

from backend.outils import code_aveugle
from backend.outils.contrat import ContexteExecution, DescriptionOutil, EchecOutil, Outil
from backend.outils.fichiers_bac import poser_fichier

NOM = "confier_a_haiku"
DELAI_S = 960.0
# Par conversation : session Claude Code reprise, et fichiers que Haiku a produits (seuls renvoyés ensuite).
_SESSIONS: dict[str, str] = {}
_PRODUITS: dict[str, set[str]] = {}

DESCRIPTION = DescriptionOutil(
    nom=NOM,
    description=(
        "Hands a coding job to Claude Haiku, who writes the files; the harness then puts them into this project "
        "at the same relative paths. Haiku sees NOTHING of the project: only your task and the files it wrote "
        "itself before. So the task must be self-contained and GENERIC: describe what to build, the files and "
        "their role, the interfaces, the tests — no project/client/business names, no absolute paths, no URLs "
        "(a task that contains them is refused). It remembers its previous jobs in this conversation, so a "
        "follow-up can be short: « tests fail: <output>, fix it ». Then YOU run the tests and check."
    ),
    parametres={"type": "object", "properties": {
        "tache": {"type": "string", "description": "The coding job, precise, complete and generic."},
    }, "required": ["tache"]},
    alias={"task": "tache", "job": "tache", "prompt": "tache", "description": "tache"},
)


def _espace(conversation_id: str) -> str:
    """Identifiant opaque de l'espace de Haiku : ne dit rien de la conversation ni du projet."""
    return hashlib.sha256(f"echohub-haiku:{conversation_id}".encode()).hexdigest()[:24]


def _nettoyer(texte: str, contexte: ContexteExecution) -> str:
    """Les chemins du projet deviennent relatifs (une sortie de test les contient) avant la garde."""
    for prefixe in (f"/projets/{contexte.projet}/", f"{contexte.racine_bac}/"):
        texte = texte.replace(prefixe, "")
    return texte


def _etat_produits(contexte: ContexteExecution) -> dict[str, str]:
    """L'état courant, dans le projet, des fichiers que Haiku a produits (l'agent a pu les retoucher)."""
    fichiers: dict[str, str] = {}
    for relatif in sorted(_PRODUITS.get(contexte.conversation_id, set())):
        chemin = (contexte.racine_bac / relatif).resolve()
        try:
            if contexte.racine_bac.resolve() in chemin.parents and chemin.is_file():
                fichiers[relatif] = chemin.read_text(errors="replace")
        except OSError as exc:
            logger.warning("Fichier produit illisible {} : {}", relatif, exc)
    return fichiers


def _garder(tache: str, fichiers: dict[str, str], contexte: ContexteExecution) -> None:
    canaris = code_aveugle.canaris(contexte.projet)
    trouve = code_aveugle.fuites_texte(tache, canaris)
    for chemin, contenu in fichiers.items():
        trouve += [f"{t} (dans {chemin})" for t in code_aveugle.fuites_texte(f"{chemin}\n{contenu}", canaris)]
    if trouve:
        logger.warning("Travail pour Haiku bloqué avant envoi : {}", trouve)
        raise EchecOutil("Refusé avant envoi : " + ", ".join(trouve[:5]) + ". Haiku ne doit rien savoir du projet : "
                         "reformule en termes génériques (ou retire ce terme du fichier concerné).")


async def _poster(charge: dict[str, Any]) -> dict[str, Any]:
    url, jeton = os.environ.get("RESUMEUR_URL", "").strip(), os.environ.get("RESUMEUR_JETON", "").strip()
    if not url or not jeton:
        raise EchecOutil("Échec : relais Claude Code non configuré. Écris le code toi-même.")
    try:
        async with httpx.AsyncClient(timeout=DELAI_S) as client:
            reponse = await client.post(f"{url}/agent", json=charge, headers={"Authorization": f"Bearer {jeton}"})
    except httpx.HTTPError as exc:
        logger.warning("Relais Claude Code injoignable : {}", exc)
        raise EchecOutil(f"Échec : relais Claude Code injoignable ({exc}). Écris le code toi-même.") from exc
    if reponse.status_code != 200:
        logger.warning("Haiku agent en échec ({}) : {}", reponse.status_code, reponse.text[:300])
        raise EchecOutil(f"Échec : Haiku n'a pas abouti ({reponse.status_code}) : {reponse.text[:300]}")
    return dict(reponse.json())


def _poser(fichiers: dict[str, Any], contexte: ContexteExecution) -> list[str]:
    """Le harnais écrit dans le projet ce que Haiku a produit — par le même chemin que `ecrire_fichier`."""
    poses: list[str] = []
    for chemin, contenu in fichiers.items():
        try:
            poser_fichier(contexte, chemin, str(contenu))
        except EchecOutil as exc:
            logger.warning("Fichier de Haiku non posé {} : {}", chemin, exc)
            continue
        poses.append(chemin)
    _PRODUITS.setdefault(contexte.conversation_id, set()).update(poses)
    return poses


async def executer(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
    if not contexte.projet:
        raise EchecOutil("Échec : le mode hybride travaille en mode projet ; cette conversation n'en a pas.")
    tache = _nettoyer(str(DESCRIPTION.normaliser(arguments).get("tache", "")).strip(), contexte)
    if not tache:
        raise EchecOutil("Échec : `tache` est requis — décris le travail de code à confier.")
    fichiers = _etat_produits(contexte)
    _garder(tache, fichiers, contexte)
    session = _SESSIONS.get(contexte.conversation_id)
    logger.info("Travail confié à Haiku (session {}) — charge envoyée :\n{}", session, tache)
    reponse = await _poster({"espace": _espace(contexte.conversation_id), "tache": tache,
                             "session": session, "fichiers": fichiers})
    if reponse.get("session"):
        _SESSIONS[contexte.conversation_id] = str(reponse["session"])
    if reponse.get("erreur"):
        raise EchecOutil(f"Échec côté Haiku : {str(reponse.get('texte', ''))[:500]}")
    poses = _poser(dict(reponse.get("fichiers") or {}), contexte)
    secondes = (reponse.get("duree_ms") or 0) / 1000
    return (f"Haiku done in {secondes:.0f} s. Files written into the project: {', '.join(poses) or 'none'}.\n\n"
            f"{reponse.get('texte', '')}\n\nNow run the tests yourself; send any failure back with confier_a_haiku.")


OUTIL = Outil(description=DESCRIPTION, executer=executer)

__all__ = ["OUTIL"]
