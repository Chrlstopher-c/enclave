"""Entrées du planificateur : métadonnées du modèle, profil machine, préférences utilisateur.

Ces structures sont le contrat d'entrée du planificateur. Toutes leurs valeurs sont **mesurées par
d'autres domaines** (`models` lit l'en-tête GGUF, `system` interroge NVML) puis injectées ici.

Le planificateur ne lit ni le disque, ni le GPU, ni `/proc` : c'est précisément ce qui le rend
testable sans matériel, donc ce qui rend détectables les défauts que la v1 n'a jamais vus.

Aucun champ n'est optionnel « au cas où » : si le domaine `models` ne sait pas lire `block_count`,
il lève `MetadonneesIllisibles` — il ne fournit pas une estimation. La v1 estimait 80 couches là où
le fichier en déclarait 41.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Moteur(str, Enum):
    """Moteur d'inférence. Les deux ne cohabitent jamais sur le GPU (cf. `COMPATIBILITE-GPU.md`)."""

    LLAMA_CPP = "llama.cpp"
    VLLM = "vllm"
    # Jamais choisi par le planificateur (Strata place lui-même ses experts) : n'apparaît que comme
    # OCCUPANT du GPU dans `ModeleCharge`, pour que son éjection soit exigée avant un autre plan.
    STRATA = "strata"


class FormatModele(str, Enum):
    """Format des poids sur disque — il détermine quel moteur peut charger le modèle."""

    GGUF = "gguf"
    SAFETENSORS = "safetensors"


class TypeCacheKV(str, Enum):
    """Quantification du cache KV. Ordre de compression croissante : F16 > Q8_0 > Q4_0.

    Trois valeurs, et pas davantage : ce sont les seuls types que le backend CUDA sait réellement
    servir COMME CACHE. Le 2026-08-16, `q2_0` et `q1_0` ont été ajoutés ici parce que ggml les
    expose — ils ont tué le processus au chargement (`SET_ROWS` non implémenté sur CUDA pour ces
    types, donc `ggml_abort()`, donc SIGABRT non rattrapable). Le gain espéré était pourtant réel :
    32 couches sur GPU au lieu de 21, à fenêtre constante. Il reste hors de portée tant que le
    backend ne sait pas écrire dans un cache de ce type.

    Voir `adaptateur_llama_cpp.TYPES_KV` : la liste y est doublée, et volontairement restrictive
    des deux côtés. Un type ne s'y ajoute qu'après un chargement ET une génération réels.
    """

    F16 = "f16"
    Q8_0 = "q8_0"
    Q4_0 = "q4_0"


class Plateforme(str, Enum):
    """Plateforme d'exécution. WSL2 est distinguée de Linux natif car leurs contraintes diffèrent."""

    LINUX_NATIF = "linux_natif"
    WSL2 = "wsl2"
    WINDOWS = "windows"


class CauseEchec(str, Enum):
    """Cause d'un échec de chargement, telle que rapportée par l'adaptateur de moteur.

    Elle sert uniquement à choisir le palier de dégradation de départ : une saturation VRAM n'appelle
    pas le même levier qu'une saturation RAM hôte.
    """

    MEMOIRE_GPU_INSUFFISANTE = "memoire_gpu_insuffisante"
    MEMOIRE_HOTE_INSUFFISANTE = "memoire_hote_insuffisante"
    CONTEXTE_REFUSE = "contexte_refuse"
    MOTEUR_INDISPONIBLE = "moteur_indisponible"
    # Le moteur n'a pas su rappeler les tenseurs d'experts en mémoire hôte. C'est la seule cause qui
    # disqualifie la STRATÉGIE de placement et non son dimensionnement : redimensionner ne servirait
    # à rien, il faut retomber sur la coupe par couches entières.
    DEPORT_EXPERTS_INDISPONIBLE = "deport_experts_indisponible"
    INCONNUE = "inconnue"


class MetadonneesModele(BaseModel):
    """Métadonnées **lues** dans le modèle, jamais déduites de son nom de fichier.

    Les clés GGUF correspondantes sont indiquées en commentaire : c'est le contrat que le domaine
    `models` doit honorer.
    """

    model_config = ConfigDict(frozen=True)

    identifiant: str
    format: FormatModele
    architecture: str = ""

    # Taille réelle du (des) fichier(s) de poids sur disque, en octets. Base du calcul du poids
    # par couche : la v1 supposait 150 Mo/couche là où la mesure donne 436 Mo.
    taille_octets: int = Field(gt=0)

    # `{arch}.block_count` — nombre RÉEL de couches transformer.
    nombre_couches: int = Field(gt=0)

    # `{arch}.embedding_length`
    dimension_embedding: int = Field(gt=0)

    # `{arch}.feed_forward_length` — dimension interne du bloc FFN, dimensionne les tampons.
    # ABSENTE sur les architectures à experts : `qwen35moe` ne déclare que
    # `{arch}.expert_feed_forward_length`, et exiger ce champ rendait le MoE de la machine
    # INCONSTRUCTIBLE, donc non planifiable. `None` plutôt qu'un repli : la largeur d'activation se
    # reconstruit alors depuis les champs d'experts (cf. `budget.largeur_activation_ffn`).
    dimension_ffn: int | None = Field(default=None, gt=0)

    # `{arch}.attention.head_count` et `.head_count_kv` (GQA : moins de têtes KV que de têtes Q).
    nombre_tetes_attention: int = Field(gt=0)
    nombre_tetes_kv: int = Field(gt=0)

    # `{arch}.attention.key_length` / `.value_length`. Absentes sur certaines architectures, où la
    # convention est `dimension_embedding / nombre_tetes_attention` — mais Qwen3 déclare un
    # `head_dim` qui NE suit PAS cette convention. Lire d'abord, dériver seulement en dernier
    # recours (cf. `budget.dimension_tete`).
    dimension_tete: int | None = Field(default=None, gt=0)

    # `{arch}.context_length` — plafond d'entraînement. Au-delà, le modèle divague.
    contexte_entrainement_max: int = Field(gt=0)

    # Longueur de `tokenizer.ggml.tokens` : dimensionne le tampon de logits.
    taille_vocabulaire: int = Field(gt=0)

    quantification: str | None = None
    est_moe: bool = False

    # ------------------------------------------------------------- mélange d'experts
    #
    # Tout ce bloc vaut `None` ou reste vide quand la mesure n'existe pas, et le planificateur
    # retombe alors sur la coupe par couches entières. Aucune de ces valeurs n'a de défaut : une
    # largeur d'expert prise pour une largeur de bloc sous-dimensionne les tampons d'un facteur 8.

    # `{arch}.expert_count` et `{arch}.expert_used_count` — mesurés à 256 et 8 sur qwen35moe.
    nombre_experts: int | None = Field(default=None, gt=0)
    nombre_experts_actifs: int | None = Field(default=None, gt=0)

    # `{arch}.expert_feed_forward_length` — largeur d'UN expert (512 mesuré). Ce n'est PAS la
    # largeur vive d'un bloc : `nombre_experts_actifs` experts sont routés ensemble à chaque token.
    dimension_ffn_expert: int | None = Field(default=None, gt=0)
    # `{arch}.expert_shared_feed_forward_length` — expert partagé (512 mesuré), actif à CHAQUE token
    # quel que soit le routage. Il compte dans le dense résident et ne se déporte jamais.
    dimension_ffn_expert_partage: int | None = Field(default=None, gt=0)

    # Poids RÉEL de chaque bloc, et dedans celui des seuls tenseurs d'experts (`ffn_*_exps`), relevés
    # sur l'index des tenseurs. Mesuré sur le 35B-A3B IQ3_M : 13,057 Gio d'experts contre 0,721 Gio
    # de dense sur 40 blocs — 90,9 % du fichier concentré dans les tenseurs dont 8 sur 256 sont lus
    # par token. C'est cette dissymétrie qui rend la coupe par couches entières mauvaise, et c'est
    # elle qui autorise le déport d'experts. Longueur exigée : `nombre_couches`, ou vide.
    octets_par_bloc: tuple[int, ...] = ()
    octets_experts_par_bloc: tuple[int, ...] = ()
    # Tenseurs hors blocs (`token_embd`, `output.weight`) : 0,592 Gio mesurés sur le même fichier.
    octets_hors_blocs: int | None = Field(default=None, ge=0)

    # `{arch}.full_attention_interval` — une couche sur N porte un cache KV, les autres portent un
    # état récurrent. Mesuré à 4 sur les DEUX modèles de la machine : 10 couches d'attention sur 40,
    # confirmé par le comptage des `attn_q.weight`. `None` = toutes les couches en portent un.
    intervalle_attention_pleine: int | None = Field(default=None, gt=0)

    # Dimensions de l'état récurrent des blocs hybrides (clés GGUF `ssm.*`). Elles décident d'un
    # poste de VRAM qui valait ZÉRO jusqu'au 2026-08-26 : 60,72 MiB sur le 35B, et quatre fois plus
    # tant que llama-server ouvrait ses quatre slots par défaut. Absentes = architecture non
    # hybride, ou métadonnées muettes : le poste vaut alors zéro à juste titre.
    dimension_interne_ssm: int | None = Field(default=None, gt=0)
    dimension_etat_ssm: int | None = Field(default=None, gt=0)
    noyau_convolution_ssm: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _verifier_coherence(self) -> MetadonneesModele:
        """Une métadonnée incohérente doit échouer ici, pas produire un plan silencieusement faux."""
        if self.nombre_tetes_kv > self.nombre_tetes_attention:
            raise ValueError(
                f"nombre_tetes_kv ({self.nombre_tetes_kv}) > nombre_tetes_attention "
                f"({self.nombre_tetes_attention}) : métadonnées contradictoires."
            )
        self._verifier_mesures_par_bloc()
        return self

    def _verifier_mesures_par_bloc(self) -> None:
        """Une mesure par bloc partielle est pire qu'absente : elle se lirait comme un modèle plus léger."""
        for nom, mesure in (
            ("octets_par_bloc", self.octets_par_bloc),
            ("octets_experts_par_bloc", self.octets_experts_par_bloc),
        ):
            if mesure and len(mesure) != self.nombre_couches:
                raise ValueError(
                    f"{nom} porte {len(mesure)} valeurs pour {self.nombre_couches} couches : "
                    "mesure incomplète, elle ne doit pas être transmise partiellement."
                )
        if not (self.octets_par_bloc and self.octets_experts_par_bloc):
            return
        for index, (total, experts) in enumerate(zip(self.octets_par_bloc, self.octets_experts_par_bloc)):
            if experts > total:
                raise ValueError(
                    f"Bloc {index} : {experts} octets d'experts pour un bloc de {total} octets."
                )


class ModeleCharge(BaseModel):
    """Modèle déjà résident sur le GPU, avec la VRAM qu'il occupe réellement.

    vLLM prééalloue sa VRAM et ne la rend qu'à l'arrêt du processus : sur 16 Go, aucune
    cohabitation n'est possible. Le planificateur traite donc le GPU comme une ressource exclusive
    et exige l'éjection de tout ce qui est listé ici.
    """

    model_config = ConfigDict(frozen=True)

    identifiant: str
    moteur: Moteur
    vram_octets: int = Field(ge=0)


class ProfilMachine(BaseModel):
    """État matériel mesuré au moment du chargement — pas au démarrage du backend.

    `vram_libre_octets` est la VRAM réellement libre : elle inclut déjà ce que consomme le bureau
    (~1,2 Go sur la machine cible). Ne rien re-soustraire à ce titre, ce serait un double comptage.
    """

    model_config = ConfigDict(frozen=True)

    plateforme: Plateforme
    index_gpu: int = Field(default=0, ge=0)
    nom_gpu: str = ""
    vram_totale_octets: int = Field(gt=0)
    vram_libre_octets: int = Field(ge=0)
    ram_libre_octets: int = Field(ge=0)
    moteurs_disponibles: tuple[Moteur, ...] = (Moteur.LLAMA_CPP,)
    modeles_charges: tuple[ModeleCharge, ...] = ()

    # Capacité de calcul CUDA, ex. (8, 6) pour Ampere, (12, 0) pour Blackwell.
    capacite_calcul: tuple[int, int] | None = None

    @model_validator(mode="after")
    def _verifier_vram(self) -> ProfilMachine:
        if self.vram_libre_octets > self.vram_totale_octets:
            raise ValueError("vram_libre_octets dépasse vram_totale_octets : mesure incohérente.")
        return self


class PreferencesUtilisateur(BaseModel):
    """Ce que l'utilisateur demande. Rien n'est garanti : tout est plafonné par la machine.

    Une préférence **plus conservatrice** que ce que la machine permet est respectée telle quelle —
    l'utilisateur a le droit de vouloir moins. Une préférence plus ambitieuse est ramenée au maximum
    tenable, et le plan explique le plafonnement.
    """

    model_config = ConfigDict(frozen=True)

    contexte: int | None = Field(default=None, gt=0)
    batch: int | None = Field(default=None, gt=0)
    couches_gpu: int | None = Field(default=None, ge=0)
    type_cache_kv: TypeCacheKV = TypeCacheKV.F16
    moteur: Moteur | None = None
    flash_attention: bool = True

    # Mémoire unifiée CUDA : utile sur Linux natif pour laisser déborder les poids, NUISIBLE sous
    # WSL2 (mesure : 20 Go de RAM occupés, VRAM figée à 2 Go). La préférence existe, la plateforme
    # tranche — cf. `environnement.py`.
    autoriser_memoire_unifiee: bool = False

    # Réserve pour la fragmentation de l'allocateur CUDA, en fraction du total alloué.
    # Valeur par défaut PRUDENTE ET NON MESURÉE sur la machine cible : c'est le seul paramètre du
    # budget qui ne se dérive pas d'une grandeur du modèle. Elle est exposée ici, justifiée dans le
    # plan, et devra être resserrée dès qu'une mesure existera.
    ratio_fragmentation: float = Field(default=0.05, ge=0.0, le=0.5)

    # Les CUDA graphs de ggml sont ACTIFS PAR DÉFAUT dans la bibliothèque compilée ; seule leur
    # désactivation s'exprime (`GGML_CUDA_DISABLE_GRAPHS=1`), il n'existe aucune variable pour les
    # réactiver explicitement. La préférence suit donc la même forme : demander `True` pose la
    # variable, `False` (défaut) ne pose rien et laisse le comportement natif de la bibliothèque.
    desactiver_cuda_graphs: bool = False


class DemandeDeChargement(BaseModel):
    """Les trois entrées réunies : c'est l'unique argument de `planifier`."""

    model_config = ConfigDict(frozen=True)

    metadonnees: MetadonneesModele
    profil: ProfilMachine
    preferences: PreferencesUtilisateur = PreferencesUtilisateur()
