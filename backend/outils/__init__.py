"""Domaine `outils` — le harnais : ce que le modèle peut faire, et ce qu'on lui dit pouvoir faire.

Interface publique. Les autres domaines importent d'ici et jamais d'un sous-module.

Le domaine existe pour supprimer un écart mesuré : sans outils déclarés, les modèles chargés ici
annoncent des capacités qu'ils n'ont pas et fabriquent des résultats. Il tient donc ensemble deux
choses qui doivent rester cohérentes — la liste réelle des outils exécutables, et le texte qui la
décrit au modèle. Une seule source, lue aux deux endroits.

Découpe interne, dans l'ordre des dépendances :

    contrat          forme d'un outil et de son résultat
    recherche_web    premier outil, adossé au domaine `recherche`
    bac_a_sable      lanceur du processus Python confiné (rlimits, changement d'utilisateur)
    balayage_bac     enregistre dans le magasin `fichiers` ce que le bac contient de nouveau
    executer_python  outil qui relie les deux, exécution Python réelle par conversation
    registre         outils disponibles et exécution d'un appel
    socle            prompt système posé avant celui de la conversation
"""

from collections.abc import Sequence

from backend.outils.bac_a_sable import LIMITES_REELLES_TEXTE
from backend.outils.contrat import DescriptionOutil, Outil, ResultatOutil
from backend.outils.registre import (
    descriptions,
    disponibles,
    executer,
    format_moteur,
    groupes,
)
from backend.outils.socle import composer, construire
from backend.outils.suivre_taches import liste_taches, taches_ouvertes


def prompt_socle(modele: str = "", actifs: Sequence[str] | None = None, projet: str | None = None) -> str:
    """Socle correspondant aux outils réellement enregistrés à cet instant.

    `modele` est l'identifiant du modèle RÉELLEMENT chargé, transmis par l'appelant : le domaine
    `outils` ne connaît pas `inference` et n'a pas à le découvrir. Vide, le socle n'affirme aucune
    identité — mieux vaut qu'il se taise que de nommer un modèle qui n'est pas celui qui répond.
    """
    return construire(descriptions(actifs), modele, projet)


def prompt_systeme(prompt_conversation: str, modele: str = "",
                   actifs: Sequence[str] | None = None, projet: str | None = None) -> str:
    """Prompt système complet : socle d'abord, prompt de la conversation ensuite.

    C'est le seul point d'entrée que la génération doit utiliser. Composer ailleurs ferait exister
    un chemin où le socle est oublié — et ce chemin serait justement celui où le modèle affabule.
    """
    return composer(prompt_socle(modele, actifs, projet), prompt_conversation)


__all__ = [
    "DescriptionOutil",
    "Outil",
    "ResultatOutil",
    "LIMITES_REELLES_TEXTE",
    "descriptions",
    "disponibles",
    "executer",
    "format_moteur",
    "groupes",
    "prompt_socle",
    "prompt_systeme",
    "liste_taches",
    "taches_ouvertes",
]
