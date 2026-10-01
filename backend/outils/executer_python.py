"""Outil `executer_python` — exécution réelle de code Python, confinée, un bac par conversation.

Suit le contrat commun (`backend/outils/contrat.py`) : reçoit des arguments validés et le
`ContexteExecution` de l'appelant, rend un texte destiné à repartir dans le contexte du modèle.
Toute la mécanique de confinement vit dans `bac_a_sable.py` ; tout le balayage post-exécution vit
dans `balayage_bac.py`. Ce module ne fait que les relier et mettre en forme le résultat.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from backend.outils.bac_a_sable import (
    chemin_dans_atelier,
    LIMITES_REELLES_TEXTE,
    CheminHorsBac,
    executer_code_confine,
    preparer_bac,
    resoudre_dans_bac,
)
from backend.outils.balayage_bac import balayer_et_enregistrer, etat_bac
from backend.outils.contrat import ContexteExecution, DescriptionOutil, EchecOutil, Outil
from backend.outils.garde_fous import CommandeRefusee, verifier_code_python

NOM = "executer_python"

# Un résultat interminable mangerait le contexte du modèle sans rien apporter de plus qu'un
# résultat tronqué et lisible : `ResultatOutil.tronque()` s'applique déjà en aval (registre.py),
# cette borne locale évite seulement de construire un texte énorme avant d'y arriver.
LONGUEUR_SORTIE_MAX = 4_000

# Descriptions et schémas EN ANGLAIS : ils sont rendus tels quels dans le gabarit du modèle, à côté
# d'exemples d'appel eux-mêmes anglais. C'est le texte qui décide de la qualité de l'appel émis.
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fichier": {
            "type": "string",
            "description": (
                "Path of a sandbox file to run, relative — `app.py`. PREFER THIS for any program "
                "you will iterate on: the file survives the call, so a later error is fixed with "
                "`modifier_fichier` instead of retyping everything."
            ),
        },
        "code": {
            "type": "string",
            "description": (
                "Python source to run directly, without going through a file. Use it only for a "
                "throwaway one-off — a quick calculation you will not need to correct. The working "
                "directory is this conversation's sandbox. Print what you want to read back: only "
                "stdout and stderr are returned."
            ),
        },
    },
    # Exactement un des deux, et le schéma le DIT plutôt que de le laisser deviner : les gabarits
    # rendent `parameters` tel quel, donc `anyOf` est lu par le modèle même quand rien ne le valide.
    "anyOf": [{"required": ["fichier"]}, {"required": ["code"]}],
}

DESCRIPTION = DescriptionOutil(
    nom=NOM,
    description=(
        "Really executes Python as ROOT in a persistent dev workshop (a separate Docker container), "
        "isolated from the user's machine by the container boundary. Use it to compute, transform "
        "data, or produce a file instead of inventing a result. You have network, and you can `pip "
        "install` packages from a shell with `executer_commande` — they stay available here. Give "
        "EITHER `fichier` — the path of a file you wrote with `ecrire_fichier`, which is the right "
        "way for anything you may need to correct — OR `code` for a one-off snippet."
    ),
    parametres=_SCHEMA,
    # `chemin` en tête, et ce n'est pas un hasard : c'est le nom que les trois outils de fichier
    # emploient, donc celui que le modèle a sous les yeux juste avant d'appeler celui-ci. Refuser
    # l'appel pour cette seule cohérence de vocabulaire serait absurde.
    alias={
        **{a: "fichier" for a in ("chemin", "nom", "nom_fichier", "path", "file", "filename", "file_path")},
        **{a: "code" for a in ("source", "script", "python", "programme")},
    },
)


def _tronque(texte: str) -> str:
    if len(texte) <= LONGUEUR_SORTIE_MAX:
        return texte
    return f"{texte[:LONGUEUR_SORTIE_MAX]}\n[sortie tronquée à {LONGUEUR_SORTIE_MAX} caractères]"


def _formater(resultat: Any, fichiers: list[Any]) -> str:
    lignes = [f"Code de retour : {resultat.code_retour} (durée : {resultat.duree_s:.2f} s)"]
    if resultat.tue_par_filet_securite:
        lignes.append("Processus tué : dépassement du temps autorisé (temps processeur ou filet de sécurité).")
    if resultat.sortie.strip():
        lignes.append(f"Sortie standard :\n{_tronque(resultat.sortie)}")
    if resultat.erreur.strip():
        lignes.append(f"Sortie d'erreur :\n{_tronque(resultat.erreur)}")
    if fichiers:
        noms = ", ".join(f"{f.nom_affiche} (id {f.id})" for f in fichiers)
        lignes.append(f"Fichier(s) produit(s), déposés dans la conversation : {noms}")
    return "\n\n".join(lignes)


# Lanceur d'un fichier du bac, exécuté par le processus confiné.
#
# Il ouvre le fichier par un chemin RELATIF, et c'est la seule chose qui compte dans ce gabarit.
# `runpy.run_path` a été essayé d'abord et écarté sur mesure (2026-08-16) : il reconvertit son
# argument en chemin ABSOLU puis le rouvre, ce qui oblige l'utilisateur confiné à traverser tous
# les dossiers parents du bac — dossiers qui ne lui appartiennent pas et qu'il n'a aucune raison
# de pouvoir traverser. Résultat mesuré : `PermissionError` sur un fichier pourtant lisible par
# lui. Un chemin relatif se résout contre le répertoire de travail que le processus détient déjà
# (le `chdir` a lieu AVANT la bascule d'utilisateur), donc aucun parent n'est retraversé.
#
# `__name__ = "__main__"` fait tourner le garde `if __name__ == "__main__":` d'un script ordinaire.
# Sans lui, lancer un fichier ne produirait rien de visible — ce qui ressemble à une panne.
_GABARIT_LANCEUR = (
    "import sys\n"
    "chemin = {chemin!r}\n"
    "with open(chemin, 'rb') as fichier:\n"
    "    source = fichier.read()\n"
    "sys.argv = [chemin]\n"
    "exec(compile(source, chemin, 'exec'), {{'__name__': '__main__', '__file__': chemin}})\n"
)


def _source_a_executer(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
    """Code à exécuter : celui d'un fichier du bac, ou celui passé directement. Lève sur refus.

    Le fichier est lancé par un lanceur généré plutôt qu'en changeant la commande du processus
    confiné : tout le confinement (rlimits, bascule d'utilisateur, répertoire de travail) vit dans
    `bac_a_sable.executer_code_confine` et n'a aucune raison d'apprendre une seconde façon de
    démarrer.
    """
    fichier = str(arguments.get("fichier", "")).strip()
    if fichier:
        cible = resoudre_dans_bac(contexte.racine_bac, fichier)
        if not cible.is_file():
            raise CheminHorsBac(f"« {fichier} » n'existe pas dans le bac. Le créer avec `ecrire_fichier`.")
        # Forme résolue puis relative : normalisée, et l'appartenance au bac vient d'être vérifiée.
        relatif = cible.relative_to(contexte.racine_bac.resolve())
        return _GABARIT_LANCEUR.format(chemin=str(relatif))
    code = str(arguments.get("code", "")).strip()
    if not code:
        raise CheminHorsBac(
            "Ni « fichier » ni « code » fourni. Donner le chemin d'un fichier du bac, ou du code à exécuter."
        )
    return code


async def executer(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
    """Exécute le code demandé dans le bac de `contexte`, balaie, rend un texte pour le modèle.

    Le sous-processus est bloquant (rlimits + `subprocess.run`) : il tourne sur un thread séparé
    (`asyncio.to_thread`) pour ne jamais geler la boucle asyncio pendant les quelques secondes
    d'exécution.
    """
    preparer_bac(contexte.racine_bac)
    try:
        code = _source_a_executer(arguments, contexte)
    except CheminHorsBac as exc:
        return f"Échec : {exc}"
    try:
        verifier_code_python(code, chemin_dans_atelier(contexte.racine_bac))
    except CommandeRefusee as exc:
        raise EchecOutil(str(exc)) from exc

    avant = etat_bac(contexte.racine_bac) if contexte.projet is None else frozenset()
    resultat = await asyncio.to_thread(executer_code_confine, code, contexte.racine_bac)
    fichiers = [] if contexte.projet else balayer_et_enregistrer(contexte.conversation_id, contexte.racine_bac, avant)
    logger.info(
        "executer_python : code_retour={} durée={:.2f}s fichiers_produits={}",
        resultat.code_retour, resultat.duree_s, len(fichiers),
    )
    return _formater(resultat, fichiers)


OUTIL = Outil(description=DESCRIPTION, executer=executer)

__all__ = ["OUTIL", "LIMITES_REELLES_TEXTE"]
