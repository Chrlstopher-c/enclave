"""Domaine `chat` — conversations en arbre, réglages, génération en streaming, annulation.

Interface publique du domaine. Les autres domaines et la couche d'assemblage n'importent que ce qui
est exporté ici ; `depot`, `generation`, `annulation`, `branches` et `adaptation_inference` sont
des internes.

Une conversation est un ARBRE de messages (`MessageChat.parent_id`) dont la vue courante est un
chemin. Rejouer ou éditer un message ouvre une branche sœur : rien n'est réécrit, rien n'est perdu.

Assemblage type dans `main.py` :

    from backend.core import init_db, setup_logging
    from backend import chat

    setup_logging()
    init_db()
    chat.initialiser()
    application.include_router(chat.routeur, prefix="/api")

Branchement du moteur d'inférence : `chat.definir_moteur(...)` avec un objet conforme au protocole
`MoteurGeneration` (voir `port_inference`). À défaut, le domaine tentera de résoudre lui-même une
fabrique `creer_moteur_chat()` exposée par `backend.inference`.
"""

from backend.chat.annulation import annuler as annuler_generation
from backend.chat.annulation import conversations_actives, est_active
from backend.chat.depot import assurer_schema_chat, chemin_jusqua, exiger_conversation, lire_reglages
from backend.chat.erreurs import (
    BrancheInvalide,
    ContratInferenceInvalide,
    GenerationDejaEnCours,
    MessageIntrouvable,
)
from backend.chat.modeles import (
    ActivationBranche,
    ArbreConversation,
    ConversationDetaillee,
    CreationConversation,
    DemandeEdition,
    DemandeGeneration,
    DemandeRejeu,
    EtatBranche,
    EvenementDebut,
    EvenementErreur,
    EvenementFin,
    EvenementFlux,
    EvenementFragment,
    MajConversation,
    MajParametres,
    MajReglages,
    MessageChat,
    ParametresEchantillonnage,
    ReglagesConversation,
    ResumeConversation,
    RoleMessage,
)
from backend.chat.port_inference import (
    FragmentTexte,
    MessageInference,
    MoteurGeneration,
    PieceJointe,
    RequeteGeneration,
    StatistiquesGeneration,
    definir_moteur,
    reinitialiser_moteur,
)
from backend.chat.routes import PREFIXE, routeur


def initialiser() -> None:
    """Prépare le domaine : tables propres au chat. À appeler après `core.init_db()`."""
    assurer_schema_chat()


__all__ = [
    # Cycle de vie
    "initialiser",
    "assurer_schema_chat",
    # Vérification d'existence, exposée pour les domaines qui référencent une conversation
    # (`backend.fichiers`, notamment) sans dupliquer cette lecture.
    "exiger_conversation",
    # Lecture d'un point de l'arbre et des réglages, pour `backend.retours` (exemples d'entraînement).
    "chemin_jusqua",
    "lire_reglages",
    # API HTTP
    "routeur",
    "PREFIXE",
    # Contrat consommé du domaine inference
    "MoteurGeneration",
    "RequeteGeneration",
    "MessageInference",
    "PieceJointe",
    "FragmentTexte",
    "StatistiquesGeneration",
    "definir_moteur",
    "reinitialiser_moteur",
    # Contrôle des générations
    "annuler_generation",
    "est_active",
    "conversations_actives",
    # Structures du domaine
    "RoleMessage",
    "ParametresEchantillonnage",
    "MajParametres",
    "ReglagesConversation",
    "MessageChat",
    "ResumeConversation",
    "ConversationDetaillee",
    "CreationConversation",
    "MajConversation",
    "MajReglages",
    "DemandeGeneration",
    "EvenementFlux",
    "EvenementDebut",
    "EvenementFragment",
    "EvenementFin",
    "EvenementErreur",
    # Branches de conversation
    "EtatBranche",
    "ArbreConversation",
    "ActivationBranche",
    "DemandeRejeu",
    "DemandeEdition",
    # Erreurs propres au domaine
    "GenerationDejaEnCours",
    "ContratInferenceInvalide",
    "MessageIntrouvable",
    "BrancheInvalide",
]
