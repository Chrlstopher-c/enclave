"""Domaine `models` — trouver, télécharger et **connaître** les modèles.

Interface publique du domaine. Les autres domaines (`inference`, `chat`, la couche API) importent
d'ici et jamais d'un sous-module : la découpe interne — lecteur binaire, interprétation, registre,
transferts — peut changer sans les toucher.

Ce que le domaine garantit à ses appelants, et notamment au planificateur de chargement :

- `lire_metadonnees` rend ce que le fichier GGUF déclare, **lu dans son en-tête**. Le nombre de
  blocs vient de `{architecture}.block_count` ou, à défaut, des index de tenseurs réellement
  présents. Aucune valeur ne dérive du nom de fichier ni du nombre de paramètres ;
- `MesuresTenseurs.octets_par_bloc` donne le poids réel de chaque bloc, calculé descripteur par
  descripteur — c'est ce qui remplace le « 150 Mo par couche » de la v1, démenti par 436 Mo mesurés ;
- `verifier_modele` confronte ce qu'un modèle déclare à ce qu'il contient, et nomme l'écart au
  lieu de laisser le moteur échouer sur un message trompeur ;
- ce qui n'est pas lisible vaut `None`. Un appelant qui reçoit `None` doit décider ; il ne reçoit
  jamais une estimation déguisée en mesure.

Découpe interne, dans l'ordre des dépendances :

    gguf_types          tables du format ggml/llama, données pures
    gguf_reader         analyse binaire de l'en-tête GGUF
    gguf_metadata       interprétation des clés et mesure du poids des tenseurs
    safetensors_reader  index réel des poids d'un modèle safetensors
    storage             chemins, tailles réelles, formats présents sur le disque
    coherence           confrontation du déclaré au présent
    discovery           recherche Hugging Face
    registry            index local, adossé à la table `modeles` de `core/db`
    download_journal    état persistant des transferts
    download_selection  quoi télécharger, combien ça pèse — fonctions pures
    download_worker     le processus fils de transfert et son nettoyage
    download            machine à états : progression, reprise, annulation
"""

from backend.core.db import ModeleEnregistre
from backend.models.coherence import (
    Incoherence,
    NiveauIncoherence,
    RapportCoherence,
    verifier_gguf,
    verifier_modele,
    verifier_safetensors,
)
from backend.models.discovery import (
    FichierDepot,
    FormatRecherche,
    MetadonneesAnnoncees,
    Ordre,
    PageRecherche,
    ResultatRecherche,
    TriRecherche,
    details,
    inventaire,
    rechercher,
)
from backend.models.download import GestionnaireTelechargements, gestionnaire
from backend.models.download_journal import (
    ETATS_ACTIFS,
    ETATS_TERMINAUX,
    EtatTelechargement,
    Telechargement,
)
from backend.models.download_selection import motifs_ignores, octets_totaux, resoudre_cible
from backend.models.gguf_metadata import (
    MesuresTenseurs,
    MetadonneesGGUF,
    ParametresAttention,
    depuis_entete,
    indices_de_blocs,
    lire_metadonnees,
)
from backend.models.gguf_reader import EnTeteGGUF, InfoTenseur, lire_entete
from backend.models.gguf_types import TraitsGGML, nom_ftype, traits_ggml
from backend.models.registry import DossierIgnore, ResumeSynchronisation
from backend.models.registry import enregistrer as enregistrer_modele
from backend.models.registry import lister as lister_modeles
from backend.models.registry import marquer_favori
from backend.models.registry import metadonnees as metadonnees_modele
from backend.models.registry import metadonnees_gguf
from backend.models.registry import metadonnees_safetensors as metadonnees_safetensors_modele
from backend.models.safetensors_metadata import MetadonneesSafetensors
from backend.models.registry import obtenir as obtenir_modele
from backend.models.registry import oublier as oublier_modele
from backend.models.registry import synchroniser as synchroniser_registre
from backend.models.registry import verifier as verifier_modele_enregistre
from backend.models.safetensors_reader import IndexSafetensors, InfoTenseurSafetensors, lire_config, lire_index
from backend.models.storage import FormatModele, dossier_modele, est_present, identifiant, taille_reelle_octets

__all__ = [
    # Métadonnées GGUF — le cœur du domaine
    "EnTeteGGUF",
    "InfoTenseur",
    "MetadonneesGGUF",
    "MesuresTenseurs",
    "ParametresAttention",
    "TraitsGGML",
    "lire_entete",
    "lire_metadonnees",
    "depuis_entete",
    "indices_de_blocs",
    "traits_ggml",
    "nom_ftype",
    # Poids safetensors
    "IndexSafetensors",
    "InfoTenseurSafetensors",
    "MetadonneesSafetensors",
    "lire_index",
    "lire_config",
    # Cohérence
    "Incoherence",
    "NiveauIncoherence",
    "RapportCoherence",
    "verifier_modele",
    "verifier_gguf",
    "verifier_safetensors",
    # Recherche Hugging Face
    "FichierDepot",
    "FormatRecherche",
    "MetadonneesAnnoncees",
    "Ordre",
    "PageRecherche",
    "ResultatRecherche",
    "TriRecherche",
    "rechercher",
    "details",
    "inventaire",
    # Téléchargements
    "ETATS_ACTIFS",
    "ETATS_TERMINAUX",
    "EtatTelechargement",
    "GestionnaireTelechargements",
    "Telechargement",
    "gestionnaire",
    "motifs_ignores",
    "octets_totaux",
    "resoudre_cible",
    # Registre local
    "ModeleEnregistre",
    "DossierIgnore",
    "ResumeSynchronisation",
    "enregistrer_modele",
    "lister_modeles",
    "marquer_favori",
    "metadonnees_modele",
    "metadonnees_gguf",
    "metadonnees_safetensors_modele",
    "obtenir_modele",
    "oublier_modele",
    "synchroniser_registre",
    "verifier_modele_enregistre",
    # Disque
    "FormatModele",
    "dossier_modele",
    "est_present",
    "identifiant",
    "taille_reelle_octets",
]
