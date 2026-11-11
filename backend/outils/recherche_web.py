"""Outil de recherche web — le premier du harnais, adossé à SearXNG en local.

Ce module traduit dans les deux sens : un appel du modèle vers le domaine `recherche`, puis les
résultats vers un texte que le modèle sait lire. Il ne contient aucune logique de recherche ; tout
ce qui touche à SearXNG appartient au domaine `recherche` et n'est vu qu'à travers son interface.

Le texte rendu porte les URL. C'est délibéré : sans elles, le modèle cite de mémoire et invente des
sources. Avec elles, l'utilisateur peut vérifier — et c'est le seul garde-fou réel contre une
réponse plausible et fausse.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from backend.outils.contrat import ContexteExecution, DescriptionOutil, Outil
from backend.recherche import CategorieRecherche, ParametresRecherche, rechercher

NOM = "recherche_web"

# Au-delà, le résultat mange le contexte sans rien apporter : les extraits SearXNG sont courts et
# les premiers résultats portent l'essentiel. Borne assumée, pas une limite du moteur.
RESULTATS_MAX = 6

# Descriptions et schémas EN ANGLAIS : ils sont rendus tels quels dans le gabarit du modèle, à côté
# d'exemples d'appel eux-mêmes anglais. C'est le texte qui décide de la qualité de l'appel émis.
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "requete": {
            "type": "string",
            "description": (
                "The search keywords. Required — a call without it does nothing. Write them as you "
                "would type them into a search engine, not as a full sentence or question. Use the "
                "language the answer is most likely written in."
            ),
        },
        "nombre_resultats": {
            "type": "integer",
            "description": f"How many results to return, from 1 to {RESULTATS_MAX}. Optional.",
            "minimum": 1,
            "maximum": RESULTATS_MAX,
        },
    },
    "required": ["requete"],
}

DESCRIPTION = DescriptionOutil(
    nom=NOM,
    description=(
        "Searches the web and returns real results with their URLs. Use it whenever the question "
        "involves current events, facts dated after your training, precise figures, or anything "
        "that must be verifiable. One call per distinct question — refine the keywords rather "
        "than repeating the same search."
    ),
    parametres=_SCHEMA,
)


def _formater(titre: str, url: str, extrait: str | None, rang: int) -> str:
    corps = (extrait or "").strip().replace("\n", " ")
    return f"[{rang}] {titre.strip()}\n{url}\n{corps}" if corps else f"[{rang}] {titre.strip()}\n{url}"


async def executer(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
    """Exécute la recherche et rend un texte destiné au contexte du modèle.

    Toute erreur est rendue comme texte plutôt que levée : le modèle doit apprendre que la
    recherche a échoué pour le dire à l'utilisateur, au lieu de recevoir un silence qu'il
    comblerait en inventant.

    `contexte` est ignoré : cet outil ne touche ni disque ni bac, il n'a besoin d'aucune identité
    de conversation. Le paramètre existe pour respecter la signature commune `Execution`.
    """
    del contexte
    requete = str(arguments.get("requete", "")).strip()
    if not requete:
        return "SEARCH NOT RUN — no keywords given. Call again with `requete`, e.g. \"httpx AsyncClient timeout\"."

    demande = arguments.get("nombre_resultats")
    nombre = demande if isinstance(demande, int) and 1 <= demande <= RESULTATS_MAX else RESULTATS_MAX
    try:
        reponse = await rechercher(
            ParametresRecherche(requete=requete, categorie=CategorieRecherche.GENERAL, nombre_resultats=nombre)
        )
    except Exception as exc:  # noqa: BLE001 — frontière : tout échec doit revenir au modèle en texte
        logger.error("Recherche web « {} » échouée : {}", requete, exc)
        return (f"SEARCH FAILED — the search engine of the harness (SearXNG) did not answer ({exc}). This is the "
                "harness, not your query and not the site you want: retrying now will fail the same way. Tell the "
                "user web search is down; meanwhile use local sources (`doc <package>`, `--help`, installed code) "
                "or `recuperer_page` on an address you already have.")

    return _rendre(requete, list(reponse.resultats)[:nombre])


def _rendre(requete: str, resultats: list[Any]) -> str:
    if not resultats:
        return (f"SEARCH EMPTY — no result for « {requete} ». The engine works; these keywords matched nothing. "
                "Do not repeat them: use FEWER and more distinctive words (package name + one key term, in "
                "English), or a different angle. Never invent a source.")

    lignes = [_formater(r.titre, r.url, r.extrait, i) for i, r in enumerate(resultats, start=1)]
    entete = f"{len(lignes)} résultat(s) pour « {requete} » :"
    return "\n\n".join([entete, *lignes])


OUTIL = Outil(description=DESCRIPTION, executer=executer)
