"""Le bloc que la maison ajoute au prompt système : instructions, index de mémoire, skills, awareness.

Tout y est BORNÉ : ce bloc est relu à chaque tour. Le détail (corps d'un skill, d'un souvenir,
AWARENESS.md) n'y entre jamais — le modèle le lit à la demande, par section, avec ses outils.
"""

from __future__ import annotations

from backend.agent.catalogue import Entree, memoire, skills
from backend.agent.maison import AWARENESS, SYSTEME, lire_texte

SYSTEME_MAX_CARACTERES = 6_000

_MODE_D_EMPLOI = """YOUR HOME (`~agent/`, shared by all your conversations — your persistent memory between sessions):
- `~agent/AWARENESS.md` lists EVERYTHING you can use: tools, MCP servers, skills, APIs, current projects.
  It is LONG: NEVER read it whole. Call `plan_fichier` on it to see its sections, then `lire_fichier`
  with `ligne_debut`/`ligne_fin` on the one section you need, or `chercher_dans_fichiers` with
  `motif: "~agent/*"`. Consult it when you wonder whether a capability exists — before saying it does not.
- Skills are reusable procedures. When a task matches one listed below, READ its SKILL.md first
  (`lire_fichier`), then follow it.
- Memory: one fact per file in `~agent/memoire/<short-name>.md`, starting with a header
  `---` / `name: …` / `description: one line` / `---`. Save there what will matter in a FUTURE
  conversation: the user's preferences, decisions and why, non-obvious facts about a project, a pitfall
  and its fix. Never save what the code or git already records. Update a file rather than duplicating it.
  The index below shows each memory's description: read the file only when it is relevant.
- You can create a skill (`~agent/skills/<name>/SKILL.md`, same header) when a procedure will recur.
- You may only WRITE under `~agent/memoire/`, `~agent/skills/` and `~agent/notes/`."""


def _liste(titre: str, entrees: list[Entree], vide: str) -> str:
    if not entrees:
        return f"{titre}\n  ({vide})"
    return f"{titre}\n" + "\n".join(f"- {e.nom} — {e.description} ({e.chemin})" for e in entrees)


def bloc_socle() -> str:
    """Bloc complet à ajouter au socle d'outils."""
    systeme = lire_texte(SYSTEME, SYSTEME_MAX_CARACTERES).strip()
    parties = [_MODE_D_EMPLOI,
               _liste("SKILLS available:", skills(), "none yet"),
               _liste("MEMORY index:", memoire(), "empty"),
               f"Capabilities: see `~agent/{AWARENESS}` (read by section)."]
    if systeme:
        parties.append(f"STANDING INSTRUCTIONS from the user (~agent/{SYSTEME}) — follow them:\n{systeme}")
    return "\n\n".join(parties)


__all__ = ["SYSTEME_MAX_CARACTERES", "bloc_socle"]
