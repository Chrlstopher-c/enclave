"""Interprétation du `config.json` d'un modèle safetensors — l'entrée du planificateur.

Symétrique de `gguf_metadata` pour l'autre format de poids. Ce que le planificateur exige est
identique quel que soit le format (nombre de couches, dimensions d'attention, contexte natif,
état récurrent des blocs hybrides) ; seule la source diffère : l'en-tête GGUF d'un côté, le
`config.json` de l'autre. Ce module produit donc les MÊMES grandeurs, lues et non devinées.

Deux pièges propres au format, tous deux payés en refus « métadonnées illisibles » avant ce module :

- **Imbrication `text_config`.** Un modèle multimodal range les dimensions du décodeur texte sous
  `config["text_config"]`, pas à la racine (`config["hidden_size"]` y vaut `None`). Lire la racine
  seule rendait vide la moitié des champs — donc un refus, alors que tout était présent un cran
  plus bas. On résout d'abord le sous-dictionnaire du texte, puis on lit dedans.
- **Attention linéaire hybride.** `qwen3_5` alterne attention pleine (une couche sur
  `full_attention_interval`) et attention linéaire de type Gated Delta Net. Cette dernière porte un
  état récurrent constant que le budget provisionne déjà via les champs `ssm.*` du planificateur ;
  il faut lui donner les bonnes dimensions. Le produit `dimension_interne × dimension_état` est
  calibré : 24 blocs récurrents = 48 MiB sur ce même 9B, mesuré sur sa variante GGUF
  (`budget.octets_etat_recurrent`). Le mapping ci-dessous reproduit ce produit à partir des clés
  `linear_*` : `num_value_heads × value_head_dim × key_head_dim`.

Le poids par bloc est **mesuré** sur l'index des tenseurs (octets réels sur disque, quantification
comprise), jamais estimé — même exigence que le chemin GGUF.
"""

from __future__ import annotations

import re
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from backend.core.errors import MetadonneesIllisibles
from backend.models.safetensors_reader import IndexSafetensors, lire_config, lire_index

# Index de bloc du décodeur : `model.language_model.layers.12.` ou `model.layers.12.` selon les
# architectures. La capture est le numéro de couche.
_MOTIF_COUCHE = re.compile(r"\.layers\.(\d+)\.")

# Tenseurs à NE PAS compter comme un bloc du décodeur, même s'ils portent `.layers.N.` : tour de
# vision d'un modèle multimodal et tête de prédiction multi-tokens (MTP). Les ranger dans un bloc
# fausserait le poids de ce bloc ; ils vont dans le hors-blocs, résident et facturé en entier.
_MOTIF_AUXILIAIRE = re.compile(r"(?:^|\.)(?:mtp|visual|vision_model|vision_tower)(?:\.|$)")


class MetadonneesSafetensors(BaseModel):
    """Ce qu'un `config.json` safetensors déclare, lu et mesuré — jamais deviné.

    Les champs que le planificateur exige strictement positifs sont ici NULLABLES : un champ absent
    vaut `None` et c'est l'assemblage de la cible (côté interface, `exiger`) qui produit un refus
    nommé, exactement comme pour le GGUF. Ce module ne comble jamais un trou par une estimation.
    """

    chemin: str
    architecture: str
    multimodal: bool = False

    # Mesuré sur l'index des tenseurs (octets réels sur disque), jamais depuis `config.json`.
    taille_octets: int = Field(ge=0)

    nombre_couches: int | None = None
    dimension_embedding: int | None = None
    dimension_ffn: int | None = None
    nombre_tetes_attention: int | None = None
    nombre_tetes_kv: int | None = None
    dimension_tete: int | None = None
    contexte_entrainement_max: int | None = None
    taille_vocabulaire: int | None = None
    quantification: str | None = None

    # Mélange d'experts — `None` sur un modèle dense, lu s'il est déclaré.
    nb_experts: int | None = None
    nb_experts_actifs: int | None = None
    dimension_ffn_expert: int | None = None
    dimension_ffn_expert_partage: int | None = None

    # Hybride : une couche sur `intervalle_attention_pleine` porte un cache KV, les autres un état
    # récurrent dont les dimensions suivent.
    intervalle_attention_pleine: int | None = None
    dimension_interne_ssm: int | None = None
    dimension_etat_ssm: int | None = None
    noyau_convolution_ssm: int | None = None

    # Poids réel par bloc, mesuré. Vide si les blocs observés ne couvrent pas exactement
    # `0..nombre_couches-1` : une mesure partielle est pire qu'absente (cf. planificateur).
    octets_par_bloc: tuple[int, ...] = ()
    octets_hors_blocs: int | None = None


def _sous_config_texte(config: dict[str, object]) -> dict[str, object]:
    """Sous-dictionnaire des dimensions du décodeur texte, ou la racine s'il n'y en a pas."""
    texte = config.get("text_config")
    return texte if isinstance(texte, dict) else config


def _entier(source: dict[str, object], cle: str) -> int | None:
    """Entier associé à une clé, ou `None` si absente, booléenne ou d'un autre type."""
    valeur = source.get(cle)
    if isinstance(valeur, bool) or not isinstance(valeur, int) or valeur <= 0:
        return None
    return valeur


def _architecture(config: dict[str, object]) -> str:
    """Nom d'architecture : `model_type` en priorité, sinon la première classe déclarée."""
    modele = config.get("model_type")
    if isinstance(modele, str) and modele:
        return modele
    architectures = config.get("architectures")
    if isinstance(architectures, list) and architectures and isinstance(architectures[0], str):
        return architectures[0]
    return "inconnue"


def _quantification(config: dict[str, object]) -> str | None:
    """Étiquette de quantification lue dans `quantization_config` (méthode et nombre de bits)."""
    quant = config.get("quantization_config")
    if not isinstance(quant, dict):
        return None
    methode = quant.get("quant_method") or quant.get("method")
    if not isinstance(methode, str):
        return None
    bits = quant.get("bits")
    if isinstance(bits, int) and not isinstance(bits, bool):
        return f"{methode}_{bits}bit"
    return methode


def _etat_recurrent(texte: dict[str, object]) -> tuple[int | None, int | None, int | None]:
    """Dimensions de l'état récurrent (Gated Delta Net), depuis les clés `linear_*`.

    `dimension_interne = num_value_heads × value_head_dim`, `dimension_état = key_head_dim` : leur
    produit est la taille de l'état par bloc, calibrée à 2 MiO/bloc sur ce 9B (`budget`). Absentes =
    attention linéaire non déclarée, donc pas de repli — le poste vaut zéro à juste titre.
    """
    tetes_valeur = _entier(texte, "linear_num_value_heads")
    dim_valeur = _entier(texte, "linear_value_head_dim")
    dim_cle = _entier(texte, "linear_key_head_dim")
    if tetes_valeur is None or dim_valeur is None or dim_cle is None:
        return None, None, None
    return tetes_valeur * dim_valeur, dim_cle, _entier(texte, "linear_conv_kernel_dim")


def _index_bloc(nom: str) -> int | None:
    """Index de bloc du décodeur pour un tenseur, ou `None` (hors décodeur, ou tour auxiliaire)."""
    if _MOTIF_AUXILIAIRE.search(nom):
        return None
    trouve = _MOTIF_COUCHE.search(nom)
    return int(trouve.group(1)) if trouve else None


def _mesurer_blocs(index: IndexSafetensors, nombre_couches: int | None) -> tuple[tuple[int, ...], int | None]:
    """Poids réel par bloc et poids hors blocs, mesurés sur l'index des tenseurs.

    Rend `((), None)` — repli sur le poids moyen — si les blocs observés ne couvrent pas exactement
    `0..nombre_couches-1` : une mesure partielle serait refusée par le planificateur, et pour cause.
    """
    par_bloc: dict[int, int] = {}
    hors_blocs = 0
    for tenseur in index.tenseurs.values():
        bloc = _index_bloc(tenseur.nom)
        if bloc is None:
            hors_blocs += tenseur.octets
        else:
            par_bloc[bloc] = par_bloc.get(bloc, 0) + tenseur.octets
    if nombre_couches is None or set(par_bloc) != set(range(nombre_couches)):
        return (), None
    return tuple(par_bloc[index_bloc] for index_bloc in range(nombre_couches)), hors_blocs


def lire_metadonnees_safetensors(dossier: Path) -> MetadonneesSafetensors:
    """Lit le `config.json` et l'index d'un modèle safetensors et en rend l'entrée du planificateur."""
    config = lire_config(dossier)
    if config is None:
        raise MetadonneesIllisibles(
            f"`config.json` absent ou illisible dans {dossier.name}.",
            remediation="Le téléchargement du modèle n'a pas abouti : le relancer depuis l'écran Modèles.",
            details={"dossier": str(dossier)},
        )
    texte = _sous_config_texte(config)
    nombre_couches = _entier(texte, "num_hidden_layers")
    index = lire_index(dossier)
    octets_par_bloc, octets_hors_blocs = _mesurer_blocs(index, nombre_couches)
    taille = index.octets_totaux
    dim_interne_ssm, dim_etat_ssm, noyau_ssm = _etat_recurrent(texte)
    tetes = _entier(texte, "num_attention_heads")

    metadonnees = MetadonneesSafetensors(
        chemin=str(dossier),
        architecture=_architecture(config),
        multimodal=isinstance(config.get("vision_config"), dict),
        taille_octets=taille,
        nombre_couches=nombre_couches,
        dimension_embedding=_entier(texte, "hidden_size"),
        dimension_ffn=_entier(texte, "intermediate_size"),
        nombre_tetes_attention=tetes,
        # GQA non déclarée = pas de GQA : les têtes KV valent les têtes Q, convention du format.
        nombre_tetes_kv=_entier(texte, "num_key_value_heads") or tetes,
        dimension_tete=_entier(texte, "head_dim"),
        contexte_entrainement_max=_entier(texte, "max_position_embeddings"),
        taille_vocabulaire=_entier(texte, "vocab_size"),
        quantification=_quantification(config),
        nb_experts=_entier(texte, "num_experts") or _entier(texte, "num_local_experts"),
        nb_experts_actifs=_entier(texte, "num_experts_per_tok"),
        dimension_ffn_expert=_entier(texte, "moe_intermediate_size"),
        dimension_ffn_expert_partage=_entier(texte, "shared_expert_intermediate_size"),
        intervalle_attention_pleine=_entier(texte, "full_attention_interval"),
        dimension_interne_ssm=dim_interne_ssm,
        dimension_etat_ssm=dim_etat_ssm,
        noyau_convolution_ssm=noyau_ssm,
        octets_par_bloc=octets_par_bloc,
        octets_hors_blocs=octets_hors_blocs,
    )
    logger.info(
        "Safetensors lu : {} — architecture {}, {} couches, contexte {}, quantification {}",
        dossier.name,
        metadonnees.architecture,
        metadonnees.nombre_couches,
        metadonnees.contexte_entrainement_max,
        metadonnees.quantification or "inconnue",
    )
    return metadonnees
