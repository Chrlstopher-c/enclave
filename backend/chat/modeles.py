"""Structures du domaine `chat` — conversations, messages, réglages, événements de flux.

Un seul endroit décrit la forme des données du domaine : la persistance (`depot`), la génération
(`generation`) et les routes HTTP (`routes`) valident toutes contre ces modèles. C'est ce qui évite
la divergence mesurée sur la v1, où le frontend, le routeur et le service portaient chacun leur
propre idée de ce qu'était une conversation.

Les valeurs par défaut d'échantillonnage reprennent celles de llama.cpp : l'utilisateur qui ne
touche à rien obtient le comportement natif du moteur, pas un réglage inventé ici.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RoleMessage = Literal["system", "user", "assistant"]

# Plafond de `max_tokens`. Il ne décrit aucun matériel : il borne la boucle de diffusion, qui
# dimensionne son nombre maximal d'itérations à partir de cette valeur.
MAX_TOKENS_PLAFOND = 262_144


class ParametresEchantillonnage(BaseModel):
    """Paramètres de génération d'une conversation. Bornes issues des plages admises par llama.cpp.

    `max_tokens` vaut `None` par défaut, et `None` signifie « aucun plafond posé ici » : le moteur
    va jusqu'à sa propre fenêtre de contexte. L'ancien défaut de 1024 était une constante inventée —
    exactement ce que la v2 bannit — et se voyait à l'usage : sur un modèle qui « réfléchit »
    longuement, la réponse finale était coupée avant d'être écrite. Une valeur non décidée vaut
    `None` et l'appelant décide, il n'y a pas de nombre par défaut défendable.
    """

    model_config = ConfigDict(extra="forbid")

    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    top_p: float = Field(default=0.95, gt=0.0, le=1.0)
    top_k: int = Field(default=40, ge=0)
    penalite_repetition: float = Field(default=1.1, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=MAX_TOKENS_PLAFOND)
    sequences_arret: list[str] = Field(default_factory=list)
    graine: int | None = Field(default=None)


class MajParametres(BaseModel):
    """Patch partiel des paramètres : seuls les champs FOURNIS sont écrits.

    Sans ce modèle, patcher la seule température supposerait de renvoyer les six autres valeurs, et
    tout oubli les ramènerait à leur défaut sans que personne ne l'ait demandé. `null` explicite
    reste une valeur de plein droit pour `max_tokens` (pas de plafond) et `graine` (aléatoire) :
    c'est la fusion, et non ce modèle, qui distingue « fourni à null » de « absent ».
    """

    model_config = ConfigDict(extra="forbid")

    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=0)
    penalite_repetition: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=MAX_TOKENS_PLAFOND)
    sequences_arret: list[str] | None = Field(default=None)
    graine: int | None = Field(default=None)


class ReglagesConversation(BaseModel):
    """Prompt système et paramètres attachés à une conversation.

    `historique_max_messages` compte des MESSAGES, jamais des tokens : le domaine `chat` ne connaît
    ni le tokenizer ni la fenêtre de contexte du modèle chargé. La v1 tronquait sur une estimation
    « 4 caractères = 1 token » — exactement le type de constante que la v2 bannit. À `None`,
    l'historique complet part au moteur, qui seul sait ce qu'il peut ingérer.
    """

    model_config = ConfigDict(extra="forbid")

    prompt_systeme: str = ""
    parametres: ParametresEchantillonnage = Field(default_factory=ParametresEchantillonnage)
    historique_max_messages: int | None = Field(default=None, ge=1)
    # Outils mis à disposition du modèle. `None` = tous ceux du registre, `[]` = aucun. La
    # distinction n'est pas cosmétique : sans elle, une conversation qui coupe tous ses outils
    # serait indiscernable d'une conversation qui n'a jamais choisi, et retrouverait les dix au
    # rechargement. Un nom inconnu du registre est ignoré à l'usage, jamais refusé à
    # l'enregistrement — un réglage écrit hier ne doit pas devenir invalide parce qu'un outil a été
    # renommé depuis.
    outils_actifs: list[str] | None = None
    # Projet confié à la conversation (dossier de la racine des projets) : le modèle y travaille
    # au lieu de son bac. `None` = conversation ordinaire.
    projet: str | None = None


class InfoCompaction(BaseModel):
    """Balise d'une compaction de contexte, telle qu'elle s'affiche dans le fil et voyage au mobile.

    CONTRAT STABLE consommé par le web ET par `echo-centre`/`EchoHubNoyau` : les noms de champs ne
    changent pas sans versionner. La compaction ne touche JAMAIS l'historique en base — elle décrit
    ce que le MOTEUR relit à la place des tours anciens. `resume` est le résumé cumulatif orienté
    agent (objectif, état, fichiers, décisions, reste à faire) ; `nb_messages_resumes` compte les
    messages du fil que ce résumé remplace côté moteur ; `tokens_avant`/`tokens_apres` chiffrent
    l'occupation de la fenêtre juste avant et juste après la compaction, `contexte_total` la fenêtre
    servie. La balise s'affiche dans le fil JUSTE AVANT le message assistant `message_id`.
    """

    id: str
    conversation_id: str
    # Message assistant dont la génération a déclenché cette compaction : la balise se rend
    # immédiatement au-dessus de lui dans le fil.
    message_id: str
    # Dernier message d'historique (identité réelle en base) replié dans le résumé. Tout ce qui suit
    # reste envoyé mot pour mot au moteur ; tout ce qui précède, y compris un résumé antérieur, est
    # remplacé par `resume`.
    coupe_message_id: str
    nb_messages_resumes: int = Field(ge=0)
    tokens_avant: int = Field(ge=0)
    tokens_apres: int = Field(ge=0)
    contexte_total: int = Field(gt=0)
    resume: str
    cree_le: datetime


class MessageChat(BaseModel):
    """Message persisté, enrichi des métadonnées propres au domaine chat.

    `tokens_generes` et `tokens_par_seconde` restent à `None` quand le moteur ne les rapporte pas :
    aucune estimation n'est fabriquée pour combler le trou.

    `parent_id` porte l'arbre : `None` désigne une racine de conversation. Deux messages de même
    parent sont deux variantes du même tour — un rejeu, une édition — et aucune ne remplace l'autre.

    `compaction` n'est peuplé que sur le message assistant dont la génération a déclenché une
    compaction : il porte alors la balise à rendre au-dessus de lui. C'est ainsi que le fil rechargé
    montre exactement ce que le direct a montré, sans liste parallèle à réordonner.
    """

    id: str
    conversation_id: str
    role: RoleMessage
    contenu: str
    tokens_generes: int | None = None
    tokens_par_seconde: float | None = None
    cree_le: datetime
    modele_id: str | None = None
    interrompu: bool = False
    parent_id: str | None = None
    compaction: InfoCompaction | None = None


class ResumeConversation(BaseModel):
    """Ligne de liste : tout sauf les messages."""

    id: str
    titre: str
    modele_id: str | None = None
    cree_le: datetime
    maj_le: datetime
    archivee: bool = False
    nb_messages: int = Field(default=0, ge=0)


class EtatBranche(BaseModel):
    """Vue courante d'une conversation : le chemin actif, et les frères de chacun de ses messages.

    `variantes` associe à chaque message du chemin la liste ORDONNÉE des identifiants qui partagent
    son parent, lui compris. C'est ce que le frontend affiche en « 2 / 3 » au survol, et ce qu'il
    renvoie à `POST /branche` pour basculer. Il n'a rien à recalculer : la position se lit avec
    `variantes[message.id].indexOf(message.id)`.
    """

    conversation_id: str
    feuille_active: str | None = None
    messages: list[MessageChat] = Field(default_factory=list)
    variantes: dict[str, list[str]] = Field(default_factory=dict)


class ArbreConversation(BaseModel):
    """Tous les messages d'une conversation, branches abandonnées comprises.

    Sert de preuve vérifiable qu'un rejeu ou une édition n'efface rien : ce que le chemin actif ne
    montre plus est toujours là, avec son `parent_id`.
    """

    conversation_id: str
    feuille_active: str | None = None
    messages: list[MessageChat] = Field(default_factory=list)


class ConversationDetaillee(BaseModel):
    """Conversation complète servie à l'ouverture d'un écran de chat.

    `messages` est le CHEMIN ACTIF, pas l'arbre entier : sur une conversation restée linéaire, la
    réponse est identique à celle d'avant les branches.
    """

    conversation: ResumeConversation
    reglages: ReglagesConversation
    messages: list[MessageChat]
    feuille_active: str | None = None
    variantes: dict[str, list[str]] = Field(default_factory=dict)


class CreationConversation(BaseModel):
    """Corps de création. Les réglages omis prennent les valeurs par défaut du domaine."""

    model_config = ConfigDict(extra="forbid")

    titre: str = Field(default="Nouvelle conversation", min_length=1, max_length=200)
    modele_id: str | None = None
    reglages: ReglagesConversation = Field(default_factory=ReglagesConversation)


class MajConversation(BaseModel):
    """Patch partiel : seuls les champs explicitement fournis sont écrits."""

    model_config = ConfigDict(extra="forbid")

    titre: str | None = Field(default=None, min_length=1, max_length=200)
    modele_id: str | None = None
    archivee: bool | None = None


class MajReglages(BaseModel):
    """Patch partiel des réglages. Fusionné avec l'existant, jamais substitué en bloc.

    `parametres` accepte un patch partiel (`MajParametres`) : envoyer l'objet complet reste valide
    et produit le même résultat, ce qui garde le contrat compatible avec le frontend existant.
    """

    model_config = ConfigDict(extra="forbid")

    prompt_systeme: str | None = None
    parametres: MajParametres | None = None
    historique_max_messages: int | None = Field(default=None, ge=1)
    # Outils mis à disposition du modèle. `None` = tous ceux du registre, `[]` = aucun. La
    # distinction n'est pas cosmétique : sans elle, une conversation qui coupe tous ses outils
    # serait indiscernable d'une conversation qui n'a jamais choisi, et retrouverait les dix au
    # rechargement. Un nom inconnu du registre est ignoré à l'usage, jamais refusé à
    # l'enregistrement — un réglage écrit hier ne doit pas devenir invalide parce qu'un outil a été
    # renommé depuis.
    outils_actifs: list[str] | None = None


class DemandeGeneration(BaseModel):
    """Tour de génération. `parametres` et `modele_id` surchargent les réglages sans les écraser.

    `fichier_ids` désigne des fichiers déjà déposés dans le magasin (`backend.fichiers`), AVANT ce
    message : le composeur envoie chaque pièce jointe dès qu'elle est choisie, puis n'en transmet que
    l'identifiant ici. Aucun octet ne traverse cette route.
    """

    model_config = ConfigDict(extra="forbid")

    contenu: str = Field(min_length=1)
    modele_id: str | None = None
    parametres: ParametresEchantillonnage | None = None
    fichier_ids: list[str] = Field(default_factory=list)


class DemandeRejeu(BaseModel):
    """Rejeu d'un message dans une nouvelle sous-branche. L'existante reste intacte."""

    model_config = ConfigDict(extra="forbid")

    modele_id: str | None = None
    parametres: ParametresEchantillonnage | None = None


class DemandeEdition(DemandeRejeu):
    """Édition d'un message utilisateur déjà envoyé : le nouveau texte ouvre une branche sœur.

    L'ancien message n'est jamais réécrit — il reste lisible dans l'arbre, avec la réponse qu'il
    avait obtenue. C'est la seule façon d'éditer sans détruire ce qui s'est réellement passé.
    """

    contenu: str = Field(min_length=1)


class ActivationBranche(BaseModel):
    """Bascule de la vue courante vers la branche qui contient ce message."""

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1)


class EvenementDebut(BaseModel):
    """Premier événement du flux : donne au client l'identifiant du message assistant à venir.

    `parent_id` dit SOUS QUEL nœud la réponse s'accroche, et `message_utilisateur_id` identifie le
    message que ce tour vient de créer, s'il en a créé un (envoi normal ou édition ; un rejeu de
    réponse n'en crée aucun). Les deux évitent au frontend de redemander la conversation entière
    pour savoir où poser le message qui arrive.
    """

    type: Literal["debut"] = "debut"
    conversation_id: str
    message_id: str
    modele_id: str | None = None
    parent_id: str | None = None
    message_utilisateur_id: str | None = None


class EvenementFragment(BaseModel):
    """Morceau de texte généré."""

    type: Literal["fragment"] = "fragment"
    texte: str


class EvenementFin(BaseModel):
    """Dernier événement : statistiques mesurées et cause de l'arrêt."""

    type: Literal["fin"] = "fin"
    message_id: str
    tokens_generes: int | None = None
    tokens_par_seconde: float | None = None
    duree_ms: int = Field(ge=0)
    interrompu: bool = False


class EvenementErreur(BaseModel):
    """Erreur survenue après l'ouverture du flux — le statut HTTP est déjà parti, pas lui."""

    type: Literal["erreur"] = "erreur"
    code: str
    message: str
    remediation: str = ""


class EvenementCompaction(BaseModel):
    """Émis quand une compaction se déclenche AVANT la génération de la réponse en cours.

    CONTRAT STABLE, décodé à l'identique par le web et par le mobile (`echo-centre`) : la charge
    porte tout ce que la balise affiche, sans second aller-retour. `message_id` est le message
    assistant à venir — celui annoncé par `EvenementDebut` — au-dessus duquel la balise se pose.
    Le fil rechargé retrouve la même balise via `MessageChat.compaction`, aux mêmes valeurs.
    """

    type: Literal["compaction"] = "compaction"
    compaction: InfoCompaction


EvenementFlux = (
    EvenementDebut | EvenementFragment | EvenementCompaction | EvenementFin | EvenementErreur
)


# Champs dont `null` est une valeur et non une absence : les remettre à zéro doit rester possible.
# `historique_max_messages` à null = historique complet ; sans cette liste, le champ serait
# réglable mais jamais effaçable.
_CHAMPS_EFFACABLES = frozenset({"historique_max_messages"})


def fusionner_parametres(actuels: ParametresEchantillonnage, patch: MajParametres) -> ParametresEchantillonnage:
    """Applique les seuls champs explicitement fournis, `null` compris.

    `exclude_unset` et non `exclude_none` : `max_tokens: null` (« pas de plafond ») et
    `graine: null` (« aléatoire ») sont des valeurs demandées, pas des champs omis. Les confondre
    rendrait ces deux réglages impossibles à effacer une fois posés.
    """
    modifications = patch.model_dump(exclude_unset=True)
    return ParametresEchantillonnage.model_validate({**actuels.model_dump(), **modifications})


def fusionner_reglages(actuels: ReglagesConversation, patch: MajReglages) -> ReglagesConversation:
    """Applique un patch partiel et revalide l'ensemble.

    Passer par `model_validate` plutôt que `model_copy` garantit que les bornes des paramètres sont
    revérifiées : un patch ne doit pas pouvoir installer une valeur qu'une création aurait refusée.
    Les paramètres sont fusionnés champ par champ, jamais remplacés en bloc.
    """
    modifications = {
        champ: valeur
        for champ, valeur in patch.model_dump(exclude_unset=True).items()
        if champ != "parametres" and (valeur is not None or champ in _CHAMPS_EFFACABLES)
    }
    parametres = actuels.parametres
    if patch.parametres is not None:
        parametres = fusionner_parametres(actuels.parametres, patch.parametres)
    fusionnes = {**actuels.model_dump(), **modifications, "parametres": parametres.model_dump()}
    return ReglagesConversation.model_validate(fusionnes)


class OutilDisponible(BaseModel):
    """Un outil du registre, tel que l'écran de sélection le présente."""

    nom: str
    description: str
    # Famille d'appartenance (`organisation`, `web`, `fichiers`, `execution`, `presentation`) : elle vient du
    # registre, seule source qui connaisse les outils réellement enregistrés.
    groupe: str
    # Coût en tokens de la DÉCLARATION de cet outil, mesuré avec le tokenizer du modèle chargé.
    # `None` quand aucun modèle ne l'est : une absence nommée, jamais un zéro — un zéro se lirait
    # comme « cet outil ne coûte rien », alors qu'un outil déclaré occupe la fenêtre à CHAQUE tour.
    tokens_definition: int | None = None


class SelectionOutils(BaseModel):
    """Outils mis à disposition du modèle pour une conversation.

    `None` signifie « tous ceux du registre », `[]` signifie « aucun ». Les confondre priverait
    d'outils une conversation qui n'a jamais choisi, ou en rendrait à celle qui les a tous coupés.
    """

    outils_actifs: list[str] | None = None
