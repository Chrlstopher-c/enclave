"""Le tour ne finit pas tant que la liste de tâches de l'agent (`suivre_taches`) a des tâches ouvertes.

C'est la version vérifiable de « ANNOUNCING IS NOT DOING » : l'annonce en prose se détecte mal (une
liste de verbes rate toujours le suivant), une tâche `a_faire` dans une liste que le modèle a lui-même
écrite ne se discute pas. N'agit que si la liste a été écrite PENDANT cette génération : une liste
restée d'un message précédent ne doit pas détourner une question sans rapport.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from backend.inference.harnais import EtatBoucle

# Relances consécutives SANS progrès (aucune tâche fermée entre deux) : au-delà, le modèle est
# vraiment bloqué et le relancer encore ne ferait que tourner.
RELANCES_TACHES_MAX = 3

CONSIGNE_TACHES_OUVERTES = (
    "Your task list still has open items: {taches}. Your turn cannot end on an open task. Do the next "
    "one NOW, starting with a tool call — then mark it `fait` with `suivre_taches` once a check proved "
    "it. If an item really needs the user, mark it `bloque` with the question in `raison`; if it no "
    "longer applies, mark it `abandonne` with the reason."
)


def relance_taches(etat: EtatBoucle) -> str | None:
    ouvertes = etat.taches_ouvertes
    if not ouvertes:
        return None
    if etat.ouvertes_a_la_relance is not None and len(ouvertes) < etat.ouvertes_a_la_relance:
        etat.relances_taches = 0
    if etat.relances_taches >= RELANCES_TACHES_MAX:
        logger.warning("Tâches encore ouvertes après {} relances sans progrès : fin du tour.", RELANCES_TACHES_MAX)
        return None
    etat.relances_taches += 1
    etat.ouvertes_a_la_relance = len(ouvertes)
    logger.warning("Fin de tour avec {} tâche(s) ouverte(s) : relance {}/{}.", len(ouvertes),
                   etat.relances_taches, RELANCES_TACHES_MAX)
    return CONSIGNE_TACHES_OUVERTES.format(taches="; ".join(f"« {t} »" for t in ouvertes[:8]))


__all__ = ["CONSIGNE_TACHES_OUVERTES", "RELANCES_TACHES_MAX", "relance_taches"]
