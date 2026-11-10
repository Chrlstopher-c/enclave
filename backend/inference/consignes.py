"""Messages glissés par l'utilisateur pendant que l'agent travaille, lus à la fin de l'étape en cours.

Demandé par Chris le 2026-11-10, « la même feature qu'ici dans Claude Code » : l'agent écrit du code ou
attend un outil ; l'utilisateur ajoute une précision sans l'arrêter. Le message attend ici, en
mémoire du processus ; la boucle le prend à la fin de l'étape (outils joués) et le donne au modèle
comme un message de l'utilisateur. Il est aussi écrit dans la réponse (`<consigne>`) : l'écran le
montre à sa place, l'historique le rend au modèle aux tours suivants, et l'interface sait qu'il a été
lu. Ce qui n'a pas été lu à la fin de la génération est jeté ici : l'interface le renvoie alors
comme un message ordinaire.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from loguru import logger

OUVRANTE, FERMANTE = "<consigne>", "</consigne>"
_ID = re.compile(r"^[\w-]{1,64}$")
LONGUEUR_MAX = 20_000


@dataclass(frozen=True)
class Consigne:
    id: str
    texte: str


_files: dict[str, list[Consigne]] = {}


def deposer(conversation_id: str, identifiant: str, texte: str) -> None:
    """Met un message en attente pour la génération en cours de cette conversation."""
    if not _ID.match(identifiant) or not texte.strip():
        raise ValueError("consigne invalide")
    _files.setdefault(conversation_id, []).append(Consigne(identifiant, texte.strip()[:LONGUEUR_MAX]))
    logger.info("Consigne glissée sur {} ({} car.)", conversation_id, len(texte))


def prendre(conversation_id: str) -> list[Consigne]:
    """Retire et rend les messages en attente, dans l'ordre d'envoi."""
    return _files.pop(conversation_id, [])


def jeter(conversation_id: str) -> None:
    """Fin de génération : ce qui reste n'a pas été lu, l'interface le renverra."""
    restes = _files.pop(conversation_id, [])
    if restes:
        logger.info("{} consigne(s) non lues sur {} : rendues à l'interface", len(restes), conversation_id)


def balise(consigne: Consigne) -> str:
    """Trace écrite dans la réponse : l'écran l'affiche, l'historique la rend au modèle."""
    return f"\n{OUVRANTE}id:{consigne.id}\n{consigne.texte}{FERMANTE}\n"


def pour_le_modele(texte: str) -> str:
    return f"[Message from the user, sent while you were working. Take it into account now.]\n\n{texte}"


__all__ = ["Consigne", "FERMANTE", "OUVRANTE", "balise", "deposer", "jeter", "pour_le_modele", "prendre"]
