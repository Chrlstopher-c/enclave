"""AWARENESS.md — tout ce que l'agent peut utiliser, régénéré depuis ce qui EXISTE vraiment.

Écrit à la main, il dériverait : un outil retiré y resterait annoncé, et le modèle le chercherait. Il
est donc reconstruit à chaque prompt depuis le registre, les skills, la mémoire, les projets et les
serveurs MCP ; seules les notes de Chris (`AWARENESS.notes.md`) sont libres. Long par nature : le
socle n'en dit que l'existence, le modèle le lit par section (`plan_fichier`).
"""

from __future__ import annotations

from collections.abc import Sequence

from loguru import logger

from backend.agent import AWARENESS, AWARENESS_NOTES, attribuer, lire_texte, memoire, racine, skills
from backend.outils.bac_a_sable import LIMITES_REELLES_TEXTE
from backend.outils.contrat import DescriptionOutil

NOTES_MAX = 20_000


def _outils(descriptions: Sequence[DescriptionOutil]) -> list[str]:
    lignes = ["## Outils", "", "Chacun est un appel d'outil ; arguments décrits dans sa déclaration.", ""]
    for d in descriptions:
        lignes += [f"### {d.nom}", d.description, ""]
    return lignes


def _projets(projet_courant: str | None) -> list[str]:
    lignes = ["## Projets", ""]
    try:
        from backend.projets import catalogue

        cat = catalogue()
    except Exception as exc:  # noqa: BLE001 — un catalogue indisponible n'empêche pas la conversation
        logger.warning("Catalogue de projets indisponible pour AWARENESS : {}", exc)
        return lignes + ["(catalogue indisponible)", ""]
    if not cat.actif:
        return lignes + ["Mode projet désactivé sur cette installation.", ""]
    lignes.append(f"Racine : {cat.racine}. Projet de CETTE conversation : {projet_courant or 'aucun'}.")
    lignes += [f"- {p.nom}" for p in cat.projets] + [""]
    return lignes


def _mcp(serveurs: Sequence[tuple[str, Sequence[str]]]) -> list[str]:
    lignes = ["## Serveurs MCP", ""]
    if not serveurs:
        return lignes + ["Aucun serveur branché (déclarer dans `~agent/mcp.json`).", ""]
    for nom, outils in serveurs:
        lignes += [f"### {nom}", *(f"- {o}" for o in outils), ""]
    return lignes


def contenu(descriptions: Sequence[DescriptionOutil], projet_courant: str | None,
            serveurs_mcp: Sequence[tuple[str, Sequence[str]]] = ()) -> str:
    lignes = ["# AWARENESS — ce que l'agent EchoHub peut utiliser", "",
              "Régénéré automatiquement à chaque conversation. Ajouts manuels : `~agent/AWARENESS.notes.md`.", ""]
    lignes += _outils(descriptions) + _mcp(serveurs_mcp)
    lignes += ["## Skills", ""] + [f"- {s.nom} — {s.description} ({s.chemin})" for s in skills()] + [""]
    souvenirs = memoire()
    lignes += ["## Mémoire", "", f"{len(souvenirs)} souvenir(s) dans `~agent/memoire/` (index dans le socle).", ""]
    lignes += _projets(projet_courant)
    lignes += ["## Environnement d'exécution", "", LIMITES_REELLES_TEXTE, ""]
    notes = lire_texte(AWARENESS_NOTES, NOTES_MAX).strip()
    if notes:
        lignes += ["## Notes de Chris", "", notes, ""]
    return "\n".join(lignes)


def regenerer(descriptions: Sequence[DescriptionOutil], projet_courant: str | None,
              serveurs_mcp: Sequence[tuple[str, Sequence[str]]] = ()) -> None:
    """Réécrit AWARENESS.md s'il a changé. Une écriture ratée se journalise, elle ne bloque rien."""
    texte = contenu(descriptions, projet_courant, serveurs_mcp)
    chemin = racine() / AWARENESS
    try:
        if not chemin.exists() or chemin.read_text(encoding="utf-8") != texte:
            chemin.write_text(texte, encoding="utf-8")
            attribuer(chemin)
    except OSError as exc:
        logger.warning("AWARENESS.md non écrit ({}) : {}", chemin, exc)


__all__ = ["contenu", "regenerer"]
