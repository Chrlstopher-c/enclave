"""Contrat commun des adaptateurs de moteurs : plan accepté, états, options, morceaux générés.

Pourquoi un contrat local plutôt qu'un import direct du planificateur : les adaptateurs doivent
rester testables sans planificateur, sans GPU et sans moteur installé, et la dépendance doit garder
un seul sens — le plan descend vers les moteurs, jamais l'inverse.

`PlanChargement` est la forme *acceptée* par les adaptateurs. `depuis_objet` valide qu'un plan
produit ailleurs la respecte : si un champ manque, l'échec est explicite et nommé, au lieu d'un
attribut lu à `None` qui se transformerait plus loin en « Failed to load model from file ».
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field


class MoteurSupporte(str, Enum):
    """Moteurs pilotés par ce sous-module. Toute autre valeur de plan est un plan invalide."""

    LLAMA_CPP = "llama.cpp"
    VLLM = "vllm"


class CauseEchec(str, Enum):
    """Qualification d'un échec de chargement.

    Existe parce que la v1 remontait « Failed to load model from file » pour tout : le message
    accusait le fichier alors que la cause était ailleurs (VRAM, moteur non compilé, contexte trop
    grand). Une cause nommée est ce qui permet au planificateur de dégrader dans la bonne direction.
    """

    VRAM_INSUFFISANTE = "vram_insuffisante"
    VRAM_NON_LIBEREE = "vram_non_liberee"
    RAM_INSUFFISANTE = "ram_insuffisante"
    CONTEXTE_TROP_GRAND = "contexte_trop_grand"
    ARCHITECTURE_INCONNUE = "architecture_inconnue"
    QUANTIFICATION_INCOMPATIBLE = "quantification_incompatible"
    FICHIER_ILLISIBLE = "fichier_illisible"
    MOTEUR_ABSENT = "moteur_absent"
    MOTEUR_SANS_CUDA = "moteur_sans_cuda"
    # Le plan demande de rappeler des tenseurs d'experts en mémoire hôte et le moteur installé ne
    # sait pas le faire, ou ne l'a pas fait. Distincte de `VRAM_INSUFFISANTE` : ce n'est pas un
    # manque de mémoire, c'est une stratégie de placement inapplicable ici.
    DEPORT_EXPERTS_INDISPONIBLE = "deport_experts_indisponible"
    PLAN_INCOMPLET = "plan_incomplet"
    DELAI_DEPASSE = "delai_depasse"
    ANNULE = "annule"
    INDETERMINEE = "indeterminee"


class EtatChargement(str, Enum):
    """États observables du superviseur. Un seul est actif à la fois, le GPU étant exclusif."""

    INACTIF = "inactif"
    EN_COURS = "en_cours"
    PRET = "pret"
    ECHOUE = "echoue"


class PlanChargement(BaseModel):
    """Plan produit par le planificateur et appliqué tel quel par un adaptateur.

    Aucun adaptateur ne recalcule une de ces valeurs : le planificateur est seule source de vérité.
    Un champ absent est une erreur de plan, pas une invitation à choisir un défaut.
    """

    # `from_attributes` accepte aussi bien un modèle pydantic du planificateur qu'un dataclass.
    model_config = ConfigDict(from_attributes=True, extra="ignore", frozen=True)

    moteur: MoteurSupporte
    chemin_modele: str
    identifiant_modele: str = ""

    couches_gpu: int = Field(description="Couches déléguées au GPU. -1 = toutes (llama.cpp).")

    # Second axe de placement, indispensable sur un MoE : index des blocs dont les tenseurs
    # `ffn_*_exps` sont rappelés en mémoire hôte alors que la couche reste sur le GPU. Quand cette
    # liste est peuplée, `couches_gpu` vaut le nombre total de blocs et ne décrit donc plus seul le
    # placement — c'est ici que se lit la part du modèle qui n'est pas en VRAM.
    experts_deportes: list[int] = Field(default_factory=list)

    contexte: int = Field(gt=0, description="Fenêtre de contexte en tokens.")
    batch: int = Field(gt=0, description="Taille de lot de prompt processing.")
    type_kv_cache: str | None = Field(default=None, description="f16, q8_0, q4_0… None = défaut moteur.")
    flash_attention: bool | None = Field(default=None, description="None = défaut moteur, sinon décision du plan.")

    # Spécifique vLLM : le moteur prélloue la VRAM, la fraction doit venir du plan (jamais du défaut
    # 0.9 de vLLM, intenable sur 16 Go partagés avec le bureau Windows).
    fraction_vram: float | None = Field(default=None, gt=0.0, le=1.0)
    mode_eager: bool = False

    variables_env: dict[str, str] = Field(default_factory=dict)
    # Lignes d'explication produites par le planificateur, transportées telles quelles jusqu'au
    # journal et à l'interface : elles sont affichées, jamais réinterprétées.
    justifications: list[str] = Field(default_factory=list)

    @property
    def nom_affiche(self) -> str:
        """Nom servi aux clients : l'identifiant du plan, à défaut le nom de fichier."""
        if self.identifiant_modele:
            return self.identifiant_modele
        return self.chemin_modele.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]

    @classmethod
    def depuis_objet(cls, objet: Any) -> PlanChargement:
        """Valide un plan venu du planificateur (objet ou dict) contre ce contrat."""
        return cls.model_validate(objet, from_attributes=True)


class PartieTexte(BaseModel):
    """Fragment de texte d'un message multimodal — c'est exactement ce que llama-cpp-python lit."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["text"] = "text"
    text: str


class PartieImageChemin(BaseModel):
    """Fragment image AVANT encodage : porte un CHEMIN disque, jamais des octets ni du base64.

    Forme intermédiaire, produite par `MoteurChat._messages_depuis` (`backend/inference/__init__.py`)
    à partir des pièces jointes du port (`chat.port_inference.PieceJointe`). Elle n'est PAS valide à
    envoyer au moteur : `adaptateur_llama_cpp` la convertit en `PartieImage` (avec un vrai data URI)
    au tout dernier moment, juste avant `create_chat_completion` — plan d'exécution, section 2.2.

    `nom_affiche` existe pour le repli sans vision (2.4) : la ligne factuelle qui remplace une
    image quand le moteur n'a pas de projecteur a besoin d'un nom lisible, pas de l'identifiant de
    fichier sur disque. Vide par défaut — le repli retombe alors sur le nom du fichier.
    """

    model_config = ConfigDict(extra="ignore")

    type: Literal["image_chemin"] = "image_chemin"
    chemin: str
    type_mime: str
    nom_affiche: str = ""


class ImageURL(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str


class PartieImage(BaseModel):
    """Forme FINALE d'une image : exactement ce que lit `MTMDChatHandler.get_image_urls`."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["image_url"] = "image_url"
    image_url: ImageURL


PartieContenu = PartieTexte | PartieImageChemin | PartieImage


class MessageChat(BaseModel):
    """Message d'une conversation, au format attendu par les deux moteurs.

    `content` est soit un texte simple (l'écrasante majorité des messages, et tout l'existant avant
    ce lot), soit une liste de parties — texte et image — pour un message multimodal. L'union garde
    `str` valide : rien de ce qui existait n'a besoin d'être réécrit.
    """

    model_config = ConfigDict(extra="ignore")

    # `tool` est le rôle des RÉSULTATS d'outils, et il est admis parce que les gabarits le gèrent —
    # vérifié le 2026-08-16 dans l'en-tête GGUF des huit modèles présents, tous portent la branche
    # `{%- elif message.role == "tool" %}` qui enveloppe le contenu dans `<tool_response>`.
    #
    # Il ne faisait pas partie du contrat jusque-là, et les résultats repartaient donc en `assistant`
    # préfixés d'un « [outil nom — résultat] ». Le modèle a fini par IMITER ce préfixe : il écrivait
    # « [outil presenter_fichier] Affichant le fichier … » en prose au lieu d'appeler l'outil, et
    # aucune carte n'apparaissait. Un format inventé dans l'historique finit toujours par être
    # reproduit ; le canal natif du gabarit est le seul que le modèle ne confond pas avec sa prose.
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[PartieContenu]


def texte_de(message: MessageChat) -> str:
    """Texte d'un message, quelle que soit sa forme — SEULE fonction du contrat à inspecter `content`.

    Concatène les parties `text` d'un contenu multimodal et ignore les parties image (chemin non
    encodé ou data URI déjà résolu) : une image ne contribue aucun texte au décompte de contexte ni
    au découpage par poste. Aucun autre endroit du code ne doit lire `message.content` à la main —
    sinon la prochaine forme de contenu cassera cinq fichiers au lieu d'un (plan d'exécution, 2.2.5).
    """
    if isinstance(message.content, str):
        return message.content
    return "".join(partie.text for partie in message.content if isinstance(partie, PartieTexte))


class OptionsGeneration(BaseModel):
    """Réglages d'échantillonnage. Ce sont des préférences de génération, pas des mesures machine."""

    model_config = ConfigDict(extra="forbid")

    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.95, gt=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=1)
    repetition_penalty: float | None = Field(default=None, gt=0.0)
    presence_penalty: float | None = Field(default=None, ge=0.0, le=2.0)
    min_p: float | None = Field(default=None, ge=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, gt=0)
    stop: list[str] = Field(default_factory=list)
    graine: int | None = None


class MorceauGeneration(BaseModel):
    """Unité du flux de génération. `fin` clôt toujours un flux qui n'a pas levé d'exception."""

    type: Literal["token", "fin", "erreur"]
    contenu: str = ""
    raison_arret: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class EtatMoteur(BaseModel):
    """Retour de `charger` : ce que le moteur sert réellement, et ce que le chargement a coûté."""

    moteur: MoteurSupporte
    modele: str
    pret: bool
    contexte: int
    couches_gpu: int
    port: int | None = None
    duree_chargement_s: float = 0.0
    vram_avant_octets: int | None = None
    vram_apres_octets: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class Sante(BaseModel):
    """Sonde d'un moteur : répond-il maintenant, et à quel coût."""

    disponible: bool
    moteur: MoteurSupporte | None = None
    modele: str | None = None
    latence_ms: float | None = None
    detail: str = ""


# --------------------------------------------------------------- fenêtre de contexte
#
# Occupation de la fenêtre de contexte du modèle chargé. Tout ce qui suit est PUR : aucune valeur
# n'est produite ici, seulement organisée. Les nombres de tokens viennent du tokenizer du modèle
# réellement chargé (`AdaptateurMoteur.compter_tokens`) — jamais d'un ratio caractères/tokens.
# La v1 tronquait sur « 4 caractères = 1 token » ; sur un vocabulaire de 248 320 entrées, cette
# constante se trompe d'un facteur qui rend l'affichage mensonger plutôt qu'approximatif.


class PosteContexte(str, Enum):
    """Postes de la décomposition. `LIBRE` est un poste à part entière, pas un reste implicite."""

    SYSTEME = "systeme"
    UTILISATEUR = "utilisateur"
    IMAGES = "images"
    ASSISTANT = "assistant"
    RAISONNEMENT = "raisonnement"
    LIBRE = "libre"


# Ordre d'affichage : de ce que l'utilisateur subit (le système, qu'il ne voit pas) vers ce qu'il
# produit, puis l'espace restant. Les images suivent immédiatement le texte utilisateur — même
# famille de coût, la pièce jointe plutôt que la frappe. Le raisonnement précède la réponse visible
# parce que c'est lui que l'utilisateur découvre comme dévoreur de budget.
ORDRE_POSTES: tuple[PosteContexte, ...] = (
    PosteContexte.SYSTEME,
    PosteContexte.UTILISATEUR,
    PosteContexte.IMAGES,
    PosteContexte.RAISONNEMENT,
    PosteContexte.ASSISTANT,
    PosteContexte.LIBRE,
)

# Balises littérales des blocs de raisonnement (famille Qwen3, DeepSeek-R1). Le domaine `chat`
# persiste le contenu brut du moteur : quand le modèle les émet, elles sont bien dans le texte.
BALISE_RAISONNEMENT_OUVRANTE = "<think>"
BALISE_RAISONNEMENT_FERMANTE = "</think>"

# Ce que le décompte ne couvre pas, dit explicitement plutôt que comblé par une estimation.
AVERTISSEMENT_GABARIT = (
    "Non compté : les marqueurs que le moteur ajoute en assemblant le prompt (balises de rôle du "
    "gabarit de conversation, BOS). llama-cpp-python n'expose pas de formatage sans génération, "
    "ce surcoût n'est donc pas mesurable ici — il n'est pas estimé."
)


class SegmentContexte(BaseModel):
    """Un fragment de texte et le poste auquel il appartient, avant comptage."""

    model_config = ConfigDict(frozen=True)

    poste: PosteContexte
    texte: str


class PartContexte(BaseModel):
    """Un poste chiffré. `part` est rapportée au contexte total, pas à la somme des postes."""

    poste: PosteContexte
    tokens: int = Field(ge=0)
    part: float = Field(ge=0.0, description="Fraction du contexte total, 0 à 1.")
    segments: int = Field(ge=0, description="Nombre de fragments cumulés dans ce poste.")


class OccupationContexte(BaseModel):
    """Ce que la conversation occupe dans la fenêtre du modèle chargé, ou pourquoi c'est inconnu.

    `mesurable` faux n'est pas une erreur : c'est l'absence de tokenizer (aucun modèle chargé,
    moteur hors processus). Les champs chiffrés restent alors à `None` — un zéro ressemblerait à
    une mesure et laisserait croire à un contexte libre.
    """

    mesurable: bool
    raison: str = ""
    moteur: MoteurSupporte | None = None
    modele: str | None = None

    # Le total de référence est le contexte SERVI, lu sur l'instance chargée, et non le contexte
    # natif du modèle (262 144 déclarés contre 32 768 appliqués, par exemple). `contexte_plan` est
    # ce que le plan demandait : l'écart entre les deux, s'il existe, est signalé, pas masqué.
    contexte_total: int | None = None
    contexte_plan: int | None = None

    tokens_mesures: int | None = None
    tokens_libres: int | None = None
    depassement_tokens: int | None = Field(
        default=None, description="Tokens au-delà de la fenêtre : la conversation n'y tient plus."
    )
    postes: list[PartContexte] = Field(default_factory=list)
    avertissements: list[str] = Field(default_factory=list)


class ComptageTokens(BaseModel):
    """Décompte rendu par un adaptateur — ou son impossibilité, nommée.

    Même forme que `Sante` : une mesure absente se déclare absente avec sa raison, elle ne se
    dégrade pas en zéro.
    """

    possible: bool
    raison: str = ""
    tokens_par_texte: list[int] = Field(default_factory=list)
    contexte_moteur: int | None = Field(
        default=None, description="Contexte réellement servi, lu sur le moteur (llama.cpp : n_ctx())."
    )


class ComptageImages(BaseModel):
    """Décompte en tokens d'images — ou son impossibilité, nommée (plan d'exécution, 2.3).

    Même discipline que `ComptageTokens`, appliquée à un contenu qui n'est pas du texte : une
    mesure absente se déclare absente avec sa raison, elle ne se dégrade JAMAIS en zéro. Le champ
    `tokens_par_image` vient du même découpage que celui qui placera l'image dans la fenêtre
    (`mtmd_tokenize` + `mtmd_input_chunk_get_n_tokens`) — jamais d'une formule sur la résolution.
    """

    possible: bool
    raison: str = ""
    tokens_par_image: list[int] = Field(default_factory=list)


def separer_raisonnement(contenu: str) -> tuple[str, str]:
    """Sépare un message assistant en (visible, raisonnement) sans perdre un seul caractère.

    Les balises restent DANS la part raisonnement : ce sont du texte renvoyé au modèle au tour
    suivant, donc des tokens réels. Un bloc jamais refermé (génération interrompue) court jusqu'à
    la fin, parce que c'est exactement ce que le moteur relira.

    Seules ces deux balises littérales sont reconnues. Un modèle qui baliserait autrement est
    compté intégralement en visible : mieux vaut un poste raisonnement vide qu'un découpage deviné.
    """
    visible: list[str] = []
    raisonnement: list[str] = []
    reste = contenu
    # Borne explicite : chaque tour consomme au moins une balise ouvrante, il ne peut donc pas y en
    # avoir plus que la longueur du texte divisée par celle de la balise.
    tours_max = len(contenu) // len(BALISE_RAISONNEMENT_OUVRANTE) + 1
    for _ in range(tours_max):
        debut = reste.find(BALISE_RAISONNEMENT_OUVRANTE)
        if debut < 0:
            break
        visible.append(reste[:debut])
        apres = reste[debut:]
        fin = apres.find(BALISE_RAISONNEMENT_FERMANTE)
        if fin < 0:
            raisonnement.append(apres)
            reste = ""
            break
        coupe = fin + len(BALISE_RAISONNEMENT_FERMANTE)
        raisonnement.append(apres[:coupe])
        reste = apres[coupe:]
    # Reliquat : texte après le dernier bloc, ou tout le texte s'il n'y avait aucune balise.
    visible.append(reste)
    return "".join(visible), "".join(raisonnement)


def decouper_segments(prompt_systeme: str, messages: Sequence[MessageChat]) -> list[SegmentContexte]:
    """Range les textes à mesurer par poste. Aucun texte vide : il coûterait un appel pour zéro."""
    segments: list[SegmentContexte] = []
    if prompt_systeme:
        segments.append(SegmentContexte(poste=PosteContexte.SYSTEME, texte=prompt_systeme))
    for message in messages:
        texte = texte_de(message)
        if not texte:
            continue
        if message.role != "assistant":
            poste = PosteContexte.SYSTEME if message.role == "system" else PosteContexte.UTILISATEUR
            segments.append(SegmentContexte(poste=poste, texte=texte))
            continue
        visible, raisonnement = separer_raisonnement(texte)
        if visible:
            segments.append(SegmentContexte(poste=PosteContexte.ASSISTANT, texte=visible))
        if raisonnement:
            segments.append(SegmentContexte(poste=PosteContexte.RAISONNEMENT, texte=raisonnement))
    return segments


def decouper_images(messages: Sequence[MessageChat]) -> list[PartieImageChemin]:
    """Pièces image d'une conversation, dans l'ordre des messages — ce que le poste `IMAGES` chiffre.

    Symétrique de `decouper_segments` pour le texte. Seules les parties encore sous forme CHEMIN
    sont retenues : c'est la forme qui traverse le port `chat` → `inference`, avant tout encodage.
    Une `PartieImage` déjà résolue (data URI) ne devrait jamais atteindre ce point — l'encodage n'a
    lieu que dans l'adaptateur, au moment de générer, jamais au moment de mesurer.
    """
    images: list[PartieImageChemin] = []
    for message in messages:
        if isinstance(message.content, str):
            continue
        images.extend(partie for partie in message.content if isinstance(partie, PartieImageChemin))
    return images


def _cumuler_par_poste(
    segments: Sequence[SegmentContexte],
    tokens_par_segment: Sequence[int],
) -> tuple[dict[PosteContexte, int], dict[PosteContexte, int]]:
    """Somme les tokens et compte les fragments de chaque poste."""
    if len(segments) != len(tokens_par_segment):
        raise ValueError(
            f"Décompte incohérent : {len(segments)} segments pour {len(tokens_par_segment)} valeurs."
        )
    tokens: dict[PosteContexte, int] = {}
    nombres: dict[PosteContexte, int] = {}
    for segment, compte in zip(segments, tokens_par_segment):
        tokens[segment.poste] = tokens.get(segment.poste, 0) + compte
        nombres[segment.poste] = nombres.get(segment.poste, 0) + 1
    return tokens, nombres


def _construire_postes(
    tokens: dict[PosteContexte, int],
    nombres: dict[PosteContexte, int],
    contexte_total: int,
) -> list[PartContexte]:
    """Chiffre chaque poste dans l'ordre d'affichage, pourcentage compris."""
    # `contexte_total` vient d'une lecture moteur, donc > 0 ; la garde évite une division par zéro
    # si un moteur futur rendait 0, sans pour autant fabriquer un total.
    reference = max(contexte_total, 1)
    return [
        PartContexte(
            poste=poste,
            tokens=tokens[poste],
            part=round(tokens[poste] / reference, 6),
            segments=nombres.get(poste, 0),
        )
        for poste in ORDRE_POSTES
        # Un poste vide n'entre pas dans la légende : il ajouterait du bruit sans rien mesurer.
        # `LIBRE` fait exception — à zéro, il dit précisément que la fenêtre est saturée.
        if poste is PosteContexte.LIBRE or tokens.get(poste, 0) > 0
    ]


def assembler_occupation(
    segments: Sequence[SegmentContexte],
    tokens_par_segment: Sequence[int],
    contexte_total: int,
    contexte_plan: int | None = None,
    moteur: MoteurSupporte | None = None,
    modele: str | None = None,
    tokens_images: int | None = None,
    nombre_images: int = 0,
) -> OccupationContexte:
    """Compose la vue chiffrée. Les pourcentages sont calculés ici, une seule fois, jamais côté client.

    `tokens_images` est `None` tant qu'aucune image n'a été mesurée — le poste `IMAGES` n'apparaît
    alors pas du tout, plutôt que d'afficher un zéro qui se confondrait avec « mesuré à zéro ».
    """
    tokens, nombres = _cumuler_par_poste(segments, tokens_par_segment)
    if tokens_images is not None:
        tokens[PosteContexte.IMAGES] = tokens_images
        nombres[PosteContexte.IMAGES] = nombre_images
    mesures = sum(tokens.values())
    tokens[PosteContexte.LIBRE] = max(0, contexte_total - mesures)
    postes = _construire_postes(tokens, nombres, contexte_total)
    return OccupationContexte(
        mesurable=True,
        moteur=moteur,
        modele=modele,
        contexte_total=contexte_total,
        contexte_plan=contexte_plan,
        tokens_mesures=mesures,
        tokens_libres=tokens[PosteContexte.LIBRE],
        depassement_tokens=max(0, mesures - contexte_total),
        postes=postes,
        avertissements=_avertissements(contexte_total, contexte_plan),
    )


def _avertissements(contexte_total: int, contexte_plan: int | None) -> list[str]:
    """Ce que le décompte ne couvre pas, et tout écart entre le plan et ce que le moteur sert."""
    lignes = [AVERTISSEMENT_GABARIT]
    if contexte_plan is not None and contexte_plan != contexte_total:
        lignes.append(
            f"Le moteur sert {contexte_total} tokens de contexte alors que le plan en demandait "
            f"{contexte_plan} : la référence affichée est celle du moteur, la seule mesurée."
        )
    return lignes
