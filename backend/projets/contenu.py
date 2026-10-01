"""Lecture seule du contenu d'un projet pour l'interface : son arborescence et un fichier.

Lu directement sur le disque de l'hôte (la racine des projets y est montée) : c'est ce que l'atelier
voit aussi, sans le coût d'un aller-retour par conteneur à chaque rafraîchissement du panneau.
"""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

from backend.projets.modeles import ArbreProjet, ContenuFichier, EntreeArbre
from backend.projets.racine import ProjetInvalide, chemin_projet

# Dossiers de dépendances, de build et d'outillage : jamais listés, ils noieraient l'arborescence.
DOSSIERS_IGNORES = frozenset({
    ".echohub", ".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "dist", "build", ".next", "target", ".cache", "coverage", ".turbo", ".parcel-cache",
})
FICHIERS_MAX = 2_000
LECTURE_MAX_OCTETS = 200_000


def arbre(nom: str) -> ArbreProjet:
    base = chemin_projet(nom)
    fichiers: list[EntreeArbre] = []
    for dossier, sous_dossiers, noms in os.walk(base):
        sous_dossiers[:] = sorted(d for d in sous_dossiers if d not in DOSSIERS_IGNORES)
        for fichier in sorted(noms):
            chemin = Path(dossier) / fichier
            try:
                taille = chemin.stat().st_size
            except OSError as exc:
                logger.debug("Fichier illisible dans l'arbre de {} : {}", nom, exc)
                continue
            fichiers.append(EntreeArbre(chemin=chemin.relative_to(base).as_posix(), taille=taille))
            if len(fichiers) >= FICHIERS_MAX:
                return ArbreProjet(fichiers=fichiers, tronque=True)
    return ArbreProjet(fichiers=fichiers)


def _resoudre(base: Path, chemin: str) -> Path:
    """Fichier `chemin` du projet, confiné à son dossier et hors dossiers réservés."""
    relatif = Path(chemin)
    if relatif.is_absolute() or ".echohub" in relatif.parts:
        raise ProjetInvalide(f"Chemin refusé : « {chemin} ».")
    cible = (base / relatif).resolve()
    if not cible.is_relative_to(base) or not cible.is_file():
        raise ProjetInvalide(f"Fichier introuvable dans le projet : « {chemin} ».")
    return cible


def lire(nom: str, chemin: str) -> ContenuFichier:
    cible = _resoudre(chemin_projet(nom), chemin)
    try:
        taille = cible.stat().st_size
        with cible.open("rb") as flux:
            octets = flux.read(LECTURE_MAX_OCTETS)
    except OSError as exc:
        logger.warning("Lecture de {} dans {} impossible : {}", chemin, nom, exc)
        raise ProjetInvalide(f"Lecture impossible : {exc}") from exc
    if b"\0" in octets[:8_000]:
        return ContenuFichier(chemin=chemin, taille=taille, contenu=None, binaire=True)
    return ContenuFichier(chemin=chemin, taille=taille, contenu=octets.decode("utf-8", errors="replace"),
                          tronque=taille > LECTURE_MAX_OCTETS)
