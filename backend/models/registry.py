"""Registre local — ce qui est réellement présent sur le disque, et ce qu'on en a lu.

Le registre est un **index**, pas la vérité. La vérité est le fichier : la table `modeles` de
`core/db` ne porte qu'un résumé (architecture, nombre de couches, contexte, quantification), et
toute métadonnée fine est relue à la demande dans l'en-tête GGUF.

Ce partage règle un problème concret de la v1 : ses métadonnées étaient recopiées en base au
téléchargement puis considérées comme définitives, y compris quand elles venaient d'une estimation.
Ici, une colonne vide signifie « pas encore mesuré » — jamais « on a supposé ». Rien n'est inscrit
qui n'ait été lu, et pour un modèle safetensors le nombre de couches inscrit est celui **observé
dans les poids**, pas celui déclaré par `config.json`, dont on sait qu'il peut mentir.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from backend.core.db import ModeleEnregistre, execute, fetch_all, fetch_one, maintenant
from backend.core.errors import MetadonneesIllisibles, ModeleIntrouvable
from backend.models.capacites import CapaciteDeduite, SignauxDepot, deduire_capacites
from backend.models.coherence import RapportCoherence, verifier_modele
from backend.models.gguf_metadata import MetadonneesGGUF, lire_metadonnees
from backend.models.safetensors_metadata import MetadonneesSafetensors, lire_metadonnees_safetensors
from backend.models.safetensors_reader import lire_config, lire_index
from backend.models.storage import (
    FormatModele,
    depot_depuis_dossier,
    detecter_format,
    dossier_modele,
    dossiers_presents,
    fichiers_gguf,
    fichiers_projecteurs,
    identifiant,
    octets_fichier,
    taille_reelle_octets,
)

# Nombre de modèles dont les métadonnées restent en mémoire. La clé inclut mtime et taille : un
# fichier remplacé invalide son entrée de lui-même, sans invalidation explicite à orchestrer.
LIMITE_CACHE_METADONNEES = 32

MOTIF_COUCHE = re.compile(r"\.layers\.(\d+)\.")

_SQL_UPSERT = """
INSERT INTO modeles (id, depot, fichier, chemin, format, taille_octets, quantification,
                     architecture, nb_couches, contexte_max, ajoute_le)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(id) DO UPDATE SET
    chemin = excluded.chemin,
    format = excluded.format,
    taille_octets = excluded.taille_octets,
    quantification = excluded.quantification,
    architecture = excluded.architecture,
    nb_couches = excluded.nb_couches,
    contexte_max = excluded.contexte_max
"""


class DossierIgnore(BaseModel):
    """Un dossier présent sur le disque mais non inscriptible, et POURQUOI.

    La raison ne vivait que dans les journaux : l'écran annonçait sept modèles sans jamais dire que
    trois dossiers avaient été écartés, ni quoi en faire. Or un fichier auxiliaire pris pour un
    modèle et un téléchargement inachevé ne se corrigent pas de la même façon — l'utilisateur ne
    peut trancher que s'il lit la cause.
    """

    dossier: str
    raison: str
    remediation: str = ""


class ResumeSynchronisation(BaseModel):
    """Ce qu'une synchronisation a corrigé entre la base et le disque."""

    entrees_supprimees: list[str] = Field(default_factory=list)
    entrees_ajoutees: list[str] = Field(default_factory=list)
    dossiers_ignores: list[DossierIgnore] = Field(default_factory=list)


@lru_cache(maxsize=LIMITE_CACHE_METADONNEES)
def _metadonnees_cachees(chemin: str, mtime_ns: int, taille: int) -> MetadonneesGGUF:
    """Lecture mémoïsée. `mtime_ns` et `taille` ne servent qu'à composer la clé de cache."""
    del mtime_ns, taille
    return lire_metadonnees(Path(chemin))


def metadonnees_gguf(chemin: Path) -> MetadonneesGGUF:
    """Métadonnées d'un fichier GGUF, relues seulement si le fichier a changé."""
    try:
        etat = chemin.stat()
    except OSError as exc:
        logger.error("Fichier de modèle inaccessible {} : {}", chemin, exc)
        raise MetadonneesIllisibles(
            f"Fichier de modèle inaccessible : {chemin.name}",
            details={"chemin": str(chemin), "cause": str(exc)},
        ) from exc
    return _metadonnees_cachees(str(chemin), etat.st_mtime_ns, etat.st_size)


def _resume_gguf(chemin: Path) -> tuple[str | None, str | None, int | None, int | None]:
    """Quantification, architecture, nombre de couches et contexte, lus dans l'en-tête."""
    metadonnees = metadonnees_gguf(chemin)
    quantification = metadonnees.quantification_mesuree or metadonnees.quantification_declaree
    return quantification, metadonnees.architecture, metadonnees.block_count, metadonnees.contexte_natif


def _couches_observees(dossier: Path) -> int | None:
    """Nombre de couches réellement décrites par les poids safetensors."""
    try:
        index = lire_index(dossier)
    except MetadonneesIllisibles as exc:
        logger.warning("Index safetensors illisible dans {} : {}", dossier, exc)
        return None
    indices = {int(trouve.group(1)) for nom in index.tenseurs if (trouve := MOTIF_COUCHE.search(nom))}
    return max(indices) + 1 if indices else None


def _resume_safetensors(dossier: Path) -> tuple[str | None, str | None, int | None, int | None]:
    """Résumé d'un modèle safetensors : ce que la config déclare, ce que les poids confirment.

    Le nombre de couches inscrit est celui **observé**. Un écart avec `num_hidden_layers` n'est pas
    corrigé en silence : il est relevé par `verifier`, qui existe pour ça.
    """
    config = lire_config(dossier) or {}
    quantification_config = config.get("quantization_config")
    methode = None
    if isinstance(quantification_config, dict):
        brut = quantification_config.get("quant_method")
        methode = str(brut).upper() if isinstance(brut, str) else None

    architectures = config.get("architectures")
    architecture = config.get("model_type")
    if not isinstance(architecture, str) and isinstance(architectures, list) and architectures:
        architecture = architectures[0] if isinstance(architectures[0], str) else None

    contexte = config.get("max_position_embeddings")
    return (
        methode,
        architecture if isinstance(architecture, str) else None,
        _couches_observees(dossier),
        contexte if isinstance(contexte, int) and not isinstance(contexte, bool) else None,
    )


def _construire(depot: str, chemin: Path, format_: FormatModele, fichier: str | None) -> ModeleEnregistre:
    """Assemble une ligne de registre à partir de ce qui est lisible sur le disque."""
    if format_ is FormatModele.GGUF:
        quantification, architecture, couches, contexte = _resume_gguf(chemin)
        taille = octets_fichier(chemin)
    else:
        quantification, architecture, couches, contexte = _resume_safetensors(chemin)
        taille = taille_reelle_octets(chemin)

    return ModeleEnregistre(
        id=identifiant(depot, fichier),
        depot=depot,
        fichier=fichier,
        chemin=str(chemin),
        format=format_.value,
        taille_octets=taille,
        quantification=quantification,
        architecture=architecture,
        nb_couches=couches,
        contexte_max=contexte,
        ajoute_le=maintenant(),
    )


def _ecrire(ligne: ModeleEnregistre) -> ModeleEnregistre:
    """Insère ou met à jour une entrée du registre."""
    execute(
        _SQL_UPSERT,
        (
            ligne.id,
            ligne.depot,
            ligne.fichier,
            ligne.chemin,
            ligne.format,
            ligne.taille_octets,
            ligne.quantification,
            ligne.architecture,
            ligne.nb_couches,
            ligne.contexte_max,
            ligne.ajoute_le.isoformat(),
        ),
    )
    return ligne


def enregistrer(depot: str, *, fichier: str | None = None) -> list[ModeleEnregistre]:
    """Inscrit au registre ce qui est présent sur le disque pour ce dépôt.

    Un dépôt GGUF peut héberger plusieurs quantifications : chacune devient une entrée distincte,
    parce que chacune se charge différemment. Un dépôt safetensors ne donne qu'une entrée.
    """
    dossier = dossier_modele(depot)
    if not dossier.is_dir():
        raise ModeleIntrouvable(
            f"Aucun dossier local pour {depot}.",
            details={"depot": depot, "chemin_attendu": str(dossier)},
        )

    # Un fichier nommé n'a de sens que pour un GGUF : c'est la seule granularité où un fichier
    # unique constitue un modèle chargeable. Pour tout le reste, l'unité est le dossier.
    if fichier is not None and fichier.lower().endswith(".gguf"):
        return [_ecrire(_construire(depot, dossier / fichier, FormatModele.GGUF, fichier))]

    format_ = detecter_format(dossier)
    if format_ is FormatModele.SAFETENSORS:
        return [_ecrire(_construire(depot, dossier, format_, None))]
    if format_ is FormatModele.GGUF:
        return [
            _ecrire(_construire(depot, chemin, FormatModele.GGUF, chemin.name)) for chemin in fichiers_gguf(dossier)
        ]

    raise ModeleIntrouvable(
        f"Aucun poids reconnu dans le dossier de {depot}.",
        remediation="Le téléchargement n'a pas abouti : le relancer depuis l'écran Modèles.",
        details={"depot": depot, "chemin": str(dossier)},
    )


def lister() -> list[ModeleEnregistre]:
    """Toutes les entrées du registre, du plus récemment ajouté au plus ancien."""
    return fetch_all(ModeleEnregistre, "SELECT * FROM modeles ORDER BY ajoute_le DESC")


def marquer_favori(identifiant_modele: str, favori: bool) -> ModeleEnregistre:
    """Pose ou retire la marque de favori. L'entrée doit exister — on ne marque pas un inconnu."""
    obtenir(identifiant_modele)  # lève ModeleIntrouvable si l'entrée n'existe pas
    execute("UPDATE modeles SET favori = ? WHERE id = ?", (1 if favori else 0, identifiant_modele))
    logger.info("Modèle {} {} des favoris", identifiant_modele, "ajouté aux" if favori else "retiré")
    return obtenir(identifiant_modele)


def obtenir(identifiant_modele: str) -> ModeleEnregistre:
    """Une entrée du registre, ou `ModeleIntrouvable`."""
    trouve = fetch_one(ModeleEnregistre, "SELECT * FROM modeles WHERE id = ?", (identifiant_modele,))
    if trouve is None:
        raise ModeleIntrouvable(
            f"Modèle « {identifiant_modele} » absent du registre.",
            details={"identifiant": identifiant_modele},
        )
    return trouve


def oublier(identifiant_modele: str) -> None:
    """Retire une entrée du registre sans toucher aux fichiers."""
    supprimees = execute("DELETE FROM modeles WHERE id = ?", (identifiant_modele,))
    logger.info("Registre : {} entrée(s) retirée(s) pour {}", supprimees, identifiant_modele)


def metadonnees(identifiant_modele: str) -> MetadonneesGGUF | None:
    """Métadonnées complètes d'un modèle GGUF du registre, ou `None` s'il n'est pas GGUF."""
    entree = obtenir(identifiant_modele)
    if entree.format != FormatModele.GGUF.value:
        return None
    return metadonnees_gguf(Path(entree.chemin))


def metadonnees_safetensors(identifiant_modele: str) -> MetadonneesSafetensors | None:
    """Entrée du planificateur pour un modèle safetensors du registre, ou `None` s'il est GGUF.

    Symétrique de `metadonnees` : `None` dit « ce n'est pas ce format », à l'appelant de décider.
    Pour un safetensors, `chemin` est le dossier du modèle (cf. `_construire`), pas un fichier.
    """
    entree = obtenir(identifiant_modele)
    if entree.format != FormatModele.SAFETENSORS.value:
        return None
    return lire_metadonnees_safetensors(Path(entree.chemin))


def verifier(identifiant_modele: str) -> RapportCoherence:
    """Confronte un modèle du registre à son propre contenu."""
    return verifier_modele(Path(obtenir(identifiant_modele).chemin))


def capacites(identifiant_modele: str) -> list[CapaciteDeduite]:
    """Capacités DÉDUITES d'un modèle local, à partir de ce qui reste visible sur le disque.

    Le registre ne conserve pas les étiquettes du Hub — elles décrivent un dépôt, pas un fichier, et
    les recopier en base reproduirait le défaut de la v1 (une déclaration figée qu'on finit par lire
    comme un fait). La déduction locale ne dispose donc que du nom du dépôt et des projecteurs
    présents à côté des poids : elle est plus pauvre que celle de la recherche, et c'est assumé.

    Une liste vide signifie « rien de reconnaissable localement », jamais « le modèle ne sait pas ».
    """
    entree = obtenir(identifiant_modele)
    dossier = dossier_modele(entree.depot)
    projecteurs = [chemin.name for chemin in fichiers_projecteurs(dossier)]
    return deduire_capacites(SignauxDepot(depot=entree.depot, fichiers=projecteurs))


def _entrees_orphelines() -> list[str]:
    """Entrées du registre dont le fichier ou le dossier a disparu du disque."""
    return [entree.id for entree in lister() if not Path(entree.chemin).exists()]


def synchroniser() -> ResumeSynchronisation:
    """Réaligne le registre sur le disque : c'est le disque qui a raison.

    Sans cela, un modèle supprimé hors de l'application laisse une entrée fantôme, et la tentative
    de chargement échoue plus tard sur une erreur de fichier introuvable — le symptôme exact
    rencontré en v1 quand un dossier disparaissait.
    """
    resume = ResumeSynchronisation()
    for orpheline in _entrees_orphelines():
        oublier(orpheline)
        resume.entrees_supprimees.append(orpheline)

    connus = {entree.depot for entree in lister()}
    for dossier in dossiers_presents():
        depot = depot_depuis_dossier(dossier.name)
        if depot in connus:
            continue
        try:
            resume.entrees_ajoutees.extend(entree.id for entree in enregistrer(depot))
        except (ModeleIntrouvable, MetadonneesIllisibles) as exc:
            logger.warning("Dossier {} non inscriptible au registre : {}", dossier.name, exc)
            resume.dossiers_ignores.append(
                DossierIgnore(
                    dossier=dossier.name,
                    raison=str(exc),
                    remediation=getattr(exc, "remediation", "") or "",
                )
            )

    logger.info(
        "Registre synchronisé : {} retirée(s), {} ajoutée(s), {} ignorée(s)",
        len(resume.entrees_supprimees),
        len(resume.entrees_ajoutees),
        len(resume.dossiers_ignores),
    )
    return resume
