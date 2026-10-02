"""Domaine `agent` : la maison partagée de l'agent (instructions, mémoire, skills, awareness, MCP)."""

from backend.agent.catalogue import Entree, memoire, skills
from backend.agent.maison import (
    AWARENESS,
    AWARENESS_NOTES,
    MCP,
    PREFIXE,
    SYSTEME,
    attribuer,
    ecriture_permise,
    lire_texte,
    racine,
)
from backend.agent.socle_agent import bloc_socle

__all__ = ["AWARENESS", "AWARENESS_NOTES", "MCP", "PREFIXE", "SYSTEME", "Entree", "attribuer", "bloc_socle",
           "ecriture_permise", "lire_texte", "memoire", "racine", "skills"]
