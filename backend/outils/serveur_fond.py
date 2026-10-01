"""Outil `serveur_fond` — lancer, surveiller et arrêter un processus qui ne rend pas la main.

Sans lui, un modèle qui construit une app web lance `bun run dev` avec `executer_commande` : l'appel
bloque jusqu'au délai maximal, puis le serveur meurt avec la commande. Il ne peut donc jamais
vérifier que son app répond. Ici le processus vit dans l'atelier, et le modèle le teste avec un
`curl http://localhost:<port>` ordinaire — même conteneur, même réseau.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from backend.outils.atelier import AtelierInjoignable, RefusProcessus, piloter_processus
from backend.outils.bac_a_sable import chemin_dans_atelier, emplacement_atelier, preparer_bac
from backend.outils.contrat import ContexteExecution, DescriptionOutil, EchecOutil, Outil
from backend.outils.garde_fous import CommandeRefusee, verifier_commande

ACTIONS = ("lancer", "journal", "arreter", "lister")

DESCRIPTION = DescriptionOutil(
    nom="serveur_fond",
    description=(
        "Runs a long-lived process in the background of the workshop (dev server, API, watcher) and "
        "lets you read its log or stop it. Use it for anything that never exits by itself, such as "
        "`bun run dev --host 0.0.0.0 --port 5173` or `uvicorn app:app --port 8000`: running those with "
        "`executer_commande` would block until timeout. After `lancer`, wait a few seconds (`sleep 3`), "
        "check the log with `journal`, then test it with `executer_commande` and `curl -s localhost:<port>`. "
        "Stop it with `arreter` when done."
    ),
    parametres={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS), "description": "What to do."},
            "nom": {"type": "string", "description": "Short name of the process, e.g. `web` or `api`."},
            "commande": {"type": "string", "description": "Shell command to start (action `lancer` only)."},
            "lignes": {"type": "integer", "description": "Log lines to return (action `journal`, default 80)."},
        },
        "required": ["action"],
    },
    alias={"name": "nom", "command": "commande", "cmd": "commande"},
)


def _formater(action: str, reponse: dict[str, Any]) -> str:
    if action == "lister":
        processus = reponse.get("processus", [])
        if not processus:
            return "Aucun processus de fond dans ce dossier."
        return "\n".join(f"- {p['nom']} : {'vivant' if p['vivant'] else 'terminé'} (pid {p['pid']}) — {p['commande']}"
                         for p in processus)
    etat = "vivant" if reponse.get("vivant") else f"terminé (code {reponse.get('code_retour')})"
    lignes = [f"Processus « {reponse.get('nom')} » : {etat}, pid {reponse.get('pid')}, "
              f"depuis {reponse.get('depuis_s')} s."]
    if reponse.get("journal"):
        lignes.append(f"Journal (fin) :\n{reponse['journal']}")
    return "\n\n".join(lignes)


def _charge(arguments: dict[str, Any], contexte: ContexteExecution, action: str) -> dict[str, object]:
    racine, sous_dossier = emplacement_atelier(contexte.racine_bac)
    nom = str(arguments.get("nom", "")).strip()
    if action != "lister" and not nom:
        raise EchecOutil('Missing `nom`. Example: {"action": "lancer", "nom": "web", "commande": "bun run dev"}')
    charge: dict[str, object] = {"racine": racine, "sous_dossier": sous_dossier, "nom": nom}
    if action == "lancer":
        commande = str(arguments.get("commande", "")).strip()
        if not commande:
            raise EchecOutil("Missing `commande` for action `lancer`.")
        try:
            verifier_commande(commande, chemin_dans_atelier(contexte.racine_bac))
        except CommandeRefusee as exc:
            raise EchecOutil(str(exc)) from exc
        charge["commande"] = commande
    if action == "journal":
        try:
            charge["lignes"] = max(1, min(400, int(arguments.get("lignes", 80))))
        except (TypeError, ValueError):
            charge["lignes"] = 80
    return charge


async def executer(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
    action = str(arguments.get("action", "")).strip().lower()
    if action not in ACTIONS:
        raise EchecOutil(f"Unknown action « {action} ». Use one of: {', '.join(ACTIONS)}.")
    preparer_bac(contexte.racine_bac)
    charge = _charge(arguments, contexte, action)
    try:
        reponse = await asyncio.to_thread(piloter_processus, action, charge)
    except (AtelierInjoignable, RefusProcessus) as exc:
        raise EchecOutil(f"Échec : {exc}") from exc
    logger.info("serveur_fond {} « {} »", action, charge.get("nom"))
    return _formater(action, reponse)


OUTIL = Outil(description=DESCRIPTION, executer=executer)

__all__ = ["OUTIL"]
