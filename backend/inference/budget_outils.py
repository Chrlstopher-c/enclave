"""Budget de tours d'outils : borne, avertissements, prolongations.

Sorti de `harnais.py` (taille). Le budget borne une boucle d'outils sans jamais couper une tâche
réelle : sous FORGE il n'a pas de plafond d'extension, seul `tours_absolus_max` arrête la boucle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from backend.inference.harnais import EtatBoucle

# Injecté à l'AVANT-DERNIER tour du budget courant, jamais au dernier : prévenir une fois qu'il
# est trop tard ne sert à rien. Le modèle apprend ainsi qu'il approche d'une borne ET ce qu'il doit
# faire pour la franchir — deux informations dont il ne dispose pas autrement, puisque rien dans sa
# conversation ne dit combien de tours il a consommés.
#
# Demandé le 2026-08-26 après un cas mesuré : la borne de six tours atteinte, le modèle se
# retrouvait au tour de clôture SANS outils déclarés, écrivait « Laisse-moi chercher autrement » et
# s'arrêtait là. Il ne pouvait pas savoir qu'on venait de lui retirer ses moyens. Un couperet muet
# fait passer pour de l'incapacité ce qui est une contrainte du harnais.
CONSIGNE_AVERTISSEMENT = (
    "Harness notice — you have made {faits} consecutive tool calls, and {restants} remain before "
    "the harness stops offering tools and asks you to answer with what you have.\n"
    "If the task genuinely needs more steps, say so in one short sentence and keep calling: the "
    "budget will be extended. If you already have what you need, stop calling and answer now."
)

# Dernier avertissement : plus aucune extension ne sera accordée. Dire qu'il reste un tour serait
# faux, et le modèle organiserait la suite sur une promesse que le harnais ne tiendra pas.
CONSIGNE_DERNIER_TOUR = (
    "Harness notice — this is your LAST tool call. No further extension will be granted. Make it "
    "count, then answer the user with what you have. Do not announce a step you will not be able "
    "to take."
)


def budget_epuise(etat: EtatBoucle) -> bool:
    """Le modèle a-t-il consommé tout son budget, extensions comprises ?

    Borne ABSOLUE et calculable d'avance : `tours_outils_max * (1 + extensions_max)`. Une extension
    accordée sans plafond ferait une boucle sans fin sur un modèle qui appelle un outil à chaque
    tour — le cas n'est pas théorique, il s'est produit six fois d'affilée le 2026-08-26 sur un
    appel que le harnais détruisait.
    """
    if etat.tours_faits >= etat.harnais.tours_absolus_max:
        logger.warning("Garde-fou de {} tours d'outils atteint : la boucle est arrêtée. "
                       "Ce plafond ne se rencontre pas sur une tâche normale — suspecter une "
                       "boucle plutôt qu'une tâche longue.", etat.harnais.tours_absolus_max)
        return True
    if etat.harnais.extensions_max is None:
        return False
    plafond = etat.harnais.tours_outils_max * (1 + etat.harnais.extensions_max)
    return etat.tours_faits >= plafond


def avertissement_du_tour(etat: EtatBoucle) -> str | None:
    """Consigne à injecter AVANT ce tour, ou `None` s'il n'y a rien à dire.

    Deux avertissements distincts, et la distinction n'est pas cosmétique : annoncer une extension
    qui ne viendra pas ferait organiser au modèle une suite que le harnais ne lui accordera pas.
    """
    if etat.harnais.extensions_max is None:
        return _avertissement_garde_fou(etat)
    restants = _restants(etat)
    if restants != 1:
        return None
    if not _extension_possible(etat):
        return CONSIGNE_DERNIER_TOUR
    if etat.averti:
        return None
    etat.averti = True
    return CONSIGNE_AVERTISSEMENT.format(faits=etat.tours_faits, restants=restants)


def _avertissement_garde_fou(etat: EtatBoucle) -> str | None:
    """Budget sans plafond : se taire, sauf au tour qui précède le garde-fou absolu.

    L'avertissement « il vous reste 1 appel » tous les dix tours faisait croire à une borne
    (2026-10-01) : le modèle voulait tout caser dans « son dernier appel », n'y arrivait pas, et
    réécrivait l'annonce sept fois. Le socle dit qu'il n'y a pas de petite borne ; le harnais aussi.
    """
    if etat.harnais.tours_absolus_max - etat.tours_faits == 1:
        return CONSIGNE_DERNIER_TOUR
    return None


def _extension_possible(etat: EtatBoucle) -> bool:
    """Une prolongation peut-elle encore être accordée ?

    `extensions_max is None` signifie « sans plafond » : seul `tours_absolus_max` arrête alors la
    boucle, et il est assez haut pour ne pas se rencontrer. Le garde-fou reste vérifié ici pour
    qu'on n'annonce jamais une extension au tour qui précède immédiatement son déclenchement.
    """
    if etat.tours_faits + etat.harnais.tours_outils_max > etat.harnais.tours_absolus_max:
        return False
    if etat.harnais.extensions_max is None:
        return True
    return etat.extensions < etat.harnais.extensions_max


def _restants(etat: EtatBoucle) -> int:
    """Tours restants dans le budget COURANT, extensions déjà accordées comprises."""
    accorde = etat.harnais.tours_outils_max * (1 + etat.extensions)
    return accorde - etat.tours_faits


def prolonger(etat: EtatBoucle) -> bool:
    """Accorde une prolongation si le modèle a été averti et continue. Rend `True` si accordée.

    L'extension ne s'accorde qu'APRÈS un avertissement : sans lui, le modèle n'a jamais eu
    l'occasion de s'arrêter, et prolonger reviendrait à ne pas avoir de borne du tout.
    """
    if not etat.averti or not _extension_possible(etat):
        return False
    etat.extensions += 1
    etat.averti = False
    logger.info("Budget d'outils prolongé (extension {}, {} tours faits) : "
                "le modèle a continué après avertissement.", etat.extensions, etat.tours_faits)
    return True


__all__ = [
    "CONSIGNE_AVERTISSEMENT",
    "CONSIGNE_DERNIER_TOUR",
    "avertissement_du_tour",
    "budget_epuise",
    "prolonger",
]
