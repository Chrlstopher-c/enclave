"""Outil `executer_commande` — une commande shell réelle, dans le bac de la conversation.

Complément d'`executer_python`, et non son doublon : ce qu'un modèle a besoin de faire déborde
régulièrement de l'interpréteur Python — compiler (`gcc`, `as`, `ld`), appeler un service avec
`curl`, cloner un dépôt, inspecter une archive. Sans cet outil, un modèle capable de la tâche
échoue sur l'absence de moyen, et le harnais est seul en cause.

Cas de référence mesuré le 2026-08-26, hors de ce projet : écrire un « Hello World » en assembleur,
l'assembler, le déposer sur un service de fichiers et rendre le lien. Trois gestes, aucun faisable
depuis `executer_python`. Les binaires nécessaires sont présents dans l'image et visibles sous le
PATH confiné — vérifié : `bash`, `gcc`, `as`, `ld`, `make`, `curl`, `git`, `python3`.

Le confinement est celui d'`executer_python`, au sens strict : même lanceur (`bac_a_sable`), même
utilisateur non privilégié, mêmes bornes de mémoire, de taille de fichier, de processus et de
descripteurs, même bac. Deux réglages diffèrent, et pour une raison mesurée plutôt que par
prudence : le temps processeur (une compilation en consomme réellement) et le filet de sécurité en
temps réel (un envoi réseau attend sans consommer de processeur).

CE QUI N'EST PAS CONFINÉ est écrit dans `LIMITES_REELLES_TEXTE` et vaut ici mot pour mot : le
réseau n'est pas coupé — la coupure a été mesurée impossible dans ce conteneur — et le système de
fichiers reste lisible au-delà du bac. Une commande peut donc joindre l'extérieur. C'est ce qui
rend l'outil utile, et c'est ce qui doit rester dit plutôt que découvert.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from backend.outils.bac_a_sable import (
    chemin_dans_atelier,
    TIMEOUT_COMMANDE_SECONDES,
    executer_commande_confinee,
    preparer_bac,
)
from backend.outils.balayage_bac import balayer_et_enregistrer, etat_bac
from backend.outils.contrat import ContexteExecution, DescriptionOutil, EchecOutil, Outil
from backend.outils.garde_fous import CommandeRefusee, verifier_commande

NOM = "executer_commande"

# Même borne locale que `executer_python` : `ResultatOutil.tronque()` s'applique en aval, celle-ci
# évite seulement de construire un texte énorme avant d'y arriver. Une commande verbeuse — une
# compilation bavarde, un `git clone` — dépasse vite quelques milliers de lignes.
LONGUEUR_SORTIE_MAX = 4_000

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "commande": {
            "type": "string",
            "description": (
                "Shell command to run, exactly as you would type it. Runs with bash as ROOT in a "
                "persistent dev workshop (a separate Docker container), with this conversation's "
                "folder as working directory. You have network and a full PATH: install what you "
                "need with `apt-get install -y <pkg>` or `pip install <pkg>` — installed packages "
                "and files persist to your next messages. Chain with `&&` when a step must only run "
                "if the previous one succeeded. Both stdout and stderr come back, with the exit code."
            ),
        },
    },
    "required": ["commande"],
}

DESCRIPTION = DescriptionOutil(
    nom=NOM,
    description=(
        "Really runs a shell command as ROOT in a persistent dev workshop (a separate Docker "
        "container), isolated from the user's machine by the container boundary. You have a real "
        "terminal, network, a full PATH and dev tools (git, gcc, make, python3, node). INSTALL "
        "whatever you need — `apt-get install -y nasm`, `pip install <pkg>` — it stays available "
        "afterwards; files and packages persist across messages. Use it for what Python cannot do "
        "directly: compile, call a service with curl, clone with git, inspect an archive. The "
        "working directory is this conversation's folder, and files produced there become files of "
        "the conversation. Returns stdout, stderr and the exit code — read the exit code before "
        "claiming the command worked."
    ),
    parametres=_SCHEMA,
    # Noms que les modèles emploient spontanément pour cet argument. Comme ailleurs, ce sont des
    # correspondances explicites et testées, jamais un appariement automatique.
    alias={a: "commande" for a in ("command", "cmd", "shell", "ligne", "commande_shell", "script")},
)


def _tronque(texte: str) -> str:
    if len(texte) <= LONGUEUR_SORTIE_MAX:
        return texte
    return f"{texte[:LONGUEUR_SORTIE_MAX]}\n[sortie tronquée à {LONGUEUR_SORTIE_MAX} caractères]"


def _formater(resultat: Any, fichiers: list[Any]) -> str:
    """Compte rendu pour le modèle. Le code de retour vient EN PREMIER, à dessein.

    Une commande qui échoue écrit souvent sur la sortie standard avant d'échouer : un modèle qui
    lit d'abord une sortie plausible conclut au succès et l'annonce. Le code de retour en tête
    supprime cette lecture — c'est le seul verdict qui ne dépend pas de l'interprétation du texte.
    """
    verdict = "succès" if resultat.code_retour == 0 else "ÉCHEC"
    lignes = [f"Code de retour : {resultat.code_retour} ({verdict}, durée : {resultat.duree_s:.2f} s)"]
    if resultat.tue_par_filet_securite:
        lignes.append(
            f"Processus tué : la commande a dépassé le délai maximal de {TIMEOUT_COMMANDE_SECONDES} s "
            "dans l'atelier."
        )
    if resultat.sortie.strip():
        lignes.append(f"Sortie standard :\n{_tronque(resultat.sortie)}")
    if resultat.erreur.strip():
        lignes.append(f"Sortie d'erreur :\n{_tronque(resultat.erreur)}")
    if not resultat.sortie.strip() and not resultat.erreur.strip():
        lignes.append("Aucune sortie. Une commande muette n'est pas une commande sans effet : "
                      "vérifier le résultat avec une seconde commande si cela compte.")
    if fichiers:
        noms = ", ".join(f"{f.nom_affiche} (id {f.id})" for f in fichiers)
        lignes.append(f"Fichier(s) produit(s), déposés dans la conversation : {noms}")
    return "\n\n".join(lignes)


async def executer(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
    """Exécute la commande dans le bac de `contexte`, balaie, rend un compte rendu au modèle.

    Le sous-processus est bloquant : il tourne sur un thread séparé pour ne pas geler la boucle
    asyncio pendant l'attente — qui peut atteindre le filet de sécurité complet sur un appel réseau.

    Un code de retour non nul lève `EchecOutil` avec le compte rendu COMPLET : le harnais a besoin
    de savoir qu'un appel n'a pas abouti (`_AUCUN_OUTIL_ABOUTI`, anti-redite), et le modèle a
    besoin de la sortie d'erreur pour corriger. Rendre un texte ordinaire ferait compter l'échec
    comme un succès — exactement le défaut que `EchecOutil` a été créé pour supprimer.
    """
    commande = str(arguments.get("commande", "")).strip()
    if not commande:
        raise EchecOutil(
            "No command given. Send the `commande` argument with the full shell line, "
            'for example: {"commande": "gcc hello.c -o hello && ./hello"}'
        )
    try:
        verifier_commande(commande, chemin_dans_atelier(contexte.racine_bac))
    except CommandeRefusee as exc:
        logger.warning("executer_commande refusée par les garde-fous : {}", exc)
        raise EchecOutil(str(exc)) from exc
    preparer_bac(contexte.racine_bac)
    # En mode projet, pas de balayage : un `bun install` crée des milliers de fichiers, qui ne sont
    # pas des livrables de la conversation — le projet sur disque EST le livrable.
    avant = etat_bac(contexte.racine_bac) if contexte.projet is None else frozenset()
    resultat = await asyncio.to_thread(executer_commande_confinee, commande, contexte.racine_bac)
    fichiers = [] if contexte.projet else balayer_et_enregistrer(contexte.conversation_id, contexte.racine_bac, avant)
    logger.info(
        "executer_commande : code_retour={} durée={:.2f}s fichiers_produits={}",
        resultat.code_retour, resultat.duree_s, len(fichiers),
    )
    compte_rendu = _formater(resultat, fichiers)
    if resultat.code_retour != 0:
        raise EchecOutil(compte_rendu)
    return compte_rendu


OUTIL = Outil(description=DESCRIPTION, executer=executer)

__all__ = ["OUTIL"]
