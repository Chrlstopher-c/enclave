"""Branchement automatique du domaine `inference` sur le port de `chat`.

Ce module est le seul endroit qui connaît le nom du domaine voisin, et il ne l'importe qu'à la
demande : `chat` reste chargeable et testable dans un environnement où `inference` n'existe pas.

Le point d'entrée cherché est une fabrique publique — `creer_moteur_chat()` ou `creer_moteur()` —
qui rend un objet conforme à `MoteurGeneration`. Rien d'autre n'est deviné : une signature
inattendue produit une erreur explicite plutôt qu'un appel au hasard. Deviner ce qu'on peut lire
est précisément la faute que la v2 corrige.

Le seul assouplissement concerne la FORME des éléments rendus : un moteur qui streame des chaînes
brutes ou des dictionnaires est normalisé ici, parce que c'est une conversion sûre et vérifiable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from importlib import import_module
from types import ModuleType

from loguru import logger

from backend.chat.erreurs import ContratInferenceInvalide
from backend.chat.port_inference import (
    ElementFlux,
    FragmentTexte,
    MessageInference,
    MoteurGeneration,
    OccupationContexte,
    RequeteGeneration,
    StatistiquesGeneration,
)

MODULE_INFERENCE = "backend.inference"
FABRIQUES_CANDIDATES = ("creer_moteur_chat", "creer_moteur")

# Clés admises pour le texte d'un fragment rendu sous forme de dictionnaire, par ordre de priorité.
_CLES_TEXTE = ("texte", "text", "content", "delta")
_CLES_STATISTIQUES = ("tokens_generes", "tokens_par_seconde")


def _charger_module() -> ModuleType | None:
    try:
        return import_module(MODULE_INFERENCE)
    except ImportError as exc:
        logger.warning("Domaine inference non importable ({}) : {}", MODULE_INFERENCE, exc)
        return None


def resoudre_moteur() -> MoteurGeneration | None:
    """Cherche une fabrique de moteur dans l'interface publique d'`inference`."""
    module = _charger_module()
    if module is None:
        return None

    for nom in FABRIQUES_CANDIDATES:
        fabrique = getattr(module, nom, None)
        if fabrique is None:
            continue
        try:
            moteur = fabrique()
        except Exception as exc:  # la fabrique touche le moteur réel : tout échec doit être tracé
            logger.error("Fabrique {}.{}() a échoué : {}", MODULE_INFERENCE, nom, exc)
            raise ContratInferenceInvalide(
                f"La fabrique {nom}() du domaine inference a échoué.",
                details={"cause": str(exc)},
            ) from exc
        logger.info("Moteur de génération résolu via {}.{}()", MODULE_INFERENCE, nom)
        return _MoteurNormalise(moteur)

    logger.warning(
        "Aucune fabrique {} trouvée dans {} — le moteur doit être branché explicitement.",
        FABRIQUES_CANDIDATES,
        MODULE_INFERENCE,
    )
    return None


def normaliser_element(element: object) -> ElementFlux | None:
    """Ramène un élément de flux quelconque au contrat de `chat`, ou `None` s'il est ignorable.

    Volontairement tolérante en entrée, stricte en sortie : ce qui n'est pas reconnu est journalisé
    et écarté plutôt que transformé en texte approximatif.
    """
    if isinstance(element, (FragmentTexte, StatistiquesGeneration)):
        return element
    if isinstance(element, str):
        return FragmentTexte(texte=element)
    if isinstance(element, dict):
        return _normaliser_dictionnaire(element)

    for cle in _CLES_TEXTE:
        valeur = getattr(element, cle, None)
        if isinstance(valeur, str):
            return FragmentTexte(texte=valeur)

    logger.debug("Élément de flux ignoré, forme inconnue : {}", type(element).__name__)
    return None


def _occupation_depuis(brut: object) -> OccupationContexte:
    """Ramène l'occupation rendue par `inference` à la forme minimale de `chat`, par attributs.

    Lecture par `getattr` comme partout à cette frontière : `chat` ne connaît pas le modèle exact
    du domaine voisin, il n'en lit que les champs dont il a besoin. Une occupation non mesurable
    reste non mesurable — ses champs chiffrés restent `None`, jamais comblés par un zéro.
    """
    mesurable = bool(getattr(brut, "mesurable", False))
    if not mesurable:
        return OccupationContexte(mesurable=False)
    return OccupationContexte(
        mesurable=True,
        contexte_total=getattr(brut, "contexte_total", None),
        tokens_mesures=getattr(brut, "tokens_mesures", None),
        tokens_libres=getattr(brut, "tokens_libres", None),
    )


def _normaliser_dictionnaire(element: dict[str, object]) -> ElementFlux | None:
    if any(cle in element for cle in _CLES_STATISTIQUES):
        tokens = element.get("tokens_generes")
        debit = element.get("tokens_par_seconde")
        return StatistiquesGeneration(
            tokens_generes=int(tokens) if isinstance(tokens, (int, float)) else None,
            tokens_par_seconde=float(debit) if isinstance(debit, (int, float)) else None,
        )
    for cle in _CLES_TEXTE:
        valeur = element.get(cle)
        if isinstance(valeur, str):
            return FragmentTexte(texte=valeur)
    logger.debug("Dictionnaire de flux ignoré, aucune clé de texte connue : {}", sorted(element))
    return None


class _MoteurNormalise:
    """Enveloppe un moteur du domaine `inference` et normalise ce qu'il rend."""

    def __init__(self, moteur: object) -> None:
        self._moteur = moteur

    def generer(self, requete: RequeteGeneration) -> AsyncIterator[ElementFlux]:
        """Ouvre le flux du moteur enveloppé. L'itérateur rendu est asynchrone, jamais une coroutine."""
        return self._flux(requete)

    async def mesurer_occupation(self, messages: Sequence[MessageInference]) -> OccupationContexte:
        """Occupation de la fenêtre pour ces messages, normalisée à la forme attendue par `chat`.

        Un moteur qui n'expose pas la mesure — un faux moteur ancien, un moteur tiers — rend une
        occupation non mesurable plutôt que de lever : `chat` ne compacte alors pas, exactement comme
        quand aucun tokenizer n'est disponible.
        """
        mesurer = getattr(self._moteur, "mesurer_occupation", None)
        if mesurer is None:
            logger.debug("Moteur {} sans mesure d'occupation : compaction inerte.", type(self._moteur).__name__)
            return OccupationContexte(mesurable=False)
        brut = await mesurer(messages)
        return _occupation_depuis(brut)

    async def resumer(
        self, a_resumer: str, resume_precedent: str, langue: str, max_tokens: int
    ) -> str | None:
        """Résumé cumulatif du moteur enveloppé, ou `None` s'il ne sait pas le produire."""
        resumer = getattr(self._moteur, "resumer", None)
        if resumer is None:
            logger.debug("Moteur {} sans résumé : compaction inerte.", type(self._moteur).__name__)
            return None
        return await resumer(a_resumer, resume_precedent, langue, max_tokens)

    async def _flux(self, requete: RequeteGeneration) -> AsyncIterator[ElementFlux]:
        source = self._ouvrir(requete)
        async for element in source:
            normalise = normaliser_element(element)
            if normalise is not None:
                yield normalise

    def _ouvrir(self, requete: RequeteGeneration) -> AsyncIterator[object]:
        generer = getattr(self._moteur, "generer", None) or getattr(self._moteur, "generate", None)
        if generer is None:
            raise ContratInferenceInvalide(
                f"Le moteur {type(self._moteur).__name__} n'expose pas de méthode `generer`."
            )
        try:
            flux = generer(requete)
        except TypeError as exc:
            logger.error("Signature de génération incompatible : {}", exc)
            raise ContratInferenceInvalide(
                "La génération du domaine inference n'accepte pas une RequeteGeneration.",
                details={"cause": str(exc)},
            ) from exc
        if not hasattr(flux, "__aiter__"):
            raise ContratInferenceInvalide(
                "La génération du domaine inference ne rend pas un itérateur asynchrone.",
                details={"type_rendu": type(flux).__name__},
            )
        return flux
