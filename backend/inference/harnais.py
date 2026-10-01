"""Conduite de la boucle d'outils — réglable, et deux conduites nommées.

Le harnais, ce n'est pas la liste des outils : c'est ce que la boucle FAIT autour d'eux — combien
de tours elle accorde, quand elle relance, quand elle considère que le modèle tourne en rond. Les
outils restent une source unique (`backend/outils/registre.py`) ; ce module ne décide que de la
conduite. Cette séparation est ce qui rend la comparaison possible : à outils constants et modèle
constant, la seule variable est la conduite, donc un écart lui est attribuable.

DEUX CONDUITES

`echohub` est la conduite d'origine, inchangée : six tours d'outils avec un couperet, une relance
sur promesse non tenue, l'anti-redite sur appel échoué. Elle est CONSERVÉE, mais n'est plus le
défaut — elle sert désormais de point de comparaison.

Le défaut est passé à `forge` le 2026-08-26, sur un cas mesuré et non sur une préférence : à une
recherche web ordinaire, la borne de six tours a été atteinte, le journal l'atteste
(« Borne de 6 tours d'outils atteinte : tour de clôture sans outil »). Le modèle s'est alors
retrouvé au tour de clôture SANS outils déclarés, a écrit « Laisse-moi chercher autrement » et s'est
arrêté là. Il ne pouvait pas savoir qu'on venait de lui retirer ses moyens : rien dans sa
conversation ne lui disait combien de tours il avait consommés. Un couperet muet fait passer pour de
l'incapacité ce qui est une contrainte du harnais.

`forge` vient du harnais d'évaluation d'agent-forge, et n'ajoute que ce qui a été mesuré comme
manquant. Trois écarts, pas un de plus :

1. VINGT tours au lieu de six. Six suffit à un aller-retour outil ; une tâche en cascade — lire un
   fichier qui désigne le suivant, quatre niveaux, puis vérifier — les épuise avant d'arriver au
   bout. Mesuré le 2026-08-26 sur la famille `cascade` d'agent-forge : les tâches utiles tiennent
   entre onze et vingt-quatre tours. Une borne atteinte ne mesure plus le modèle, elle mesure la
   borne.

2. RELANCE SUR TOUR MUET. `promesse_non_tenue` écarte le tour vide par construction
   (`if not fin: return False`) : elle cherche une annonce, et un tour vide n'annonce rien. Le cas
   existe pourtant — mesuré le 2026-08-25 sur la webapp d'agent-forge, où le modèle rendait un tour
   de raisonnement pur, sans un mot de réponse. Les deux détections sont complémentaires, jamais
   redondantes : l'une regarde ce qui a été promis, l'autre qu'il y ait quelque chose.

3. ANTI-RADOTAGE SUR LE TEXTE. L'anti-redite d'origine (`_REDITE`) borne les APPELS échoués
   identiques. Elle ne voit pas un modèle qui réécrit trois fois le même paragraphe sans jamais
   appeler d'outil — mesuré le 2026-08-25, et invisible précisément parce que la détection ne
   regardait que les appels. Deux tours consécutifs au texte identique suffisent à le dire.

Ce que `forge` NE change PAS, et c'est délibéré : l'anti-redite sur appels, la consigne de clôture
quand rien n'a abouti, la reprise sur troncature. Ces trois mécanismes sont mesurés et bons ; les
remplacer par nos équivalents aurait été du remplacement, pas du portage.
"""

from __future__ import annotations

import re

from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from backend.inference.engines_adapters.contrat import MessageChat, OptionsGeneration
from backend.inference.fin_projet import (
    CONSIGNE_CODE_MONTRE,
    CONSIGNE_RESTE_FAISABLE,
    CONSIGNE_SUITE_PROJET,
    RELANCES_RESTE_MAX,
    DernierAppel,
    code_montre,
    finit_sur_futur_proche,
    pause_sans_bilan,
    rappel_dernier_appel,
    reste_faisable,
    visible,
)
from backend.inference.budget_outils import (
    CONSIGNE_AVERTISSEMENT,
    CONSIGNE_DERNIER_TOUR,
    avertissement_du_tour,
    budget_epuise,
    prolonger,
)
from backend.inference.harnais_outils import _sans_appels_outils
from backend.inference.suivi_taches import relance_taches
from backend.inference.reprise import (
    RELANCES_PROMESSE_MAX,
    consigne_promesse,
    promesse_non_tenue,
)

# Sous ce seuil, un tour est tenu pour muet : le modèle n'a pas répondu, il a seulement réfléchi.
# Quarante caractères, parce qu'une vraie réponse courte — « Oui, la version 3.12 le permet. » —
# les dépasse, alors qu'un fragment resté en suspens ne les atteint pas. Mesuré sur la webapp
# d'agent-forge : abaisser à zéro laissait passer les tours de raisonnement pur, monter à cent
# relançait des réponses complètes.
MIN_REPONSE_CARACTERES = 40

# Deux tours consécutifs identiques suffisent. Trois laissait l'utilisateur regarder la même
# réponse s'écrire une fois de trop avant que le harnais ne réagisse.
RADOTAGE_TOURS = 2

# Comparaison sur le texte normalisé : un modèle qui radote ne recopie pas au caractère près, il
# reproduit la même phrase avec une ponctuation ou une espace de différence.
_NORMALISATION = re.compile(r"\s+")


class Harnais(BaseModel):
    """Réglages de conduite d'une boucle d'outils. Immuable : c'est une constante nommée."""

    model_config = ConfigDict(frozen=True)

    nom: str
    # Tours d'outils CONSÉCUTIFS accordés avant l'avertissement. Ce n'est pas un quota par
    # conversation : le modèle qui rend la main puis repart a de nouveau tout son budget.
    tours_outils_max: int = Field(ge=2, le=60)
    # Prolongations accordées quand le modèle continue APRÈS avoir été averti.
    #
    # `None` = AUCUN plafond de prolongation : tant que le modèle continue d'appeler des outils
    # après avoir été averti, il est prolongé. C'est le comportement voulu pour un agent — une
    # tâche réelle enchaîne parfois des dizaines d'étapes, et un couperet à quarante tours
    # arrêterait le travail au milieu pour une raison qui n'a rien à voir avec la tâche.
    #
    # Ce qui borne alors la boucle n'est pas un compte d'extensions mais `tours_absolus_max`, et
    # c'est un garde-fou de sûreté, pas un budget : il ne se rencontre pas en usage normal. Il
    # existe parce qu'une boucle sans borne est un défaut en soi — et le cas n'est pas théorique,
    # le 2026-08-26 le modèle a rappelé six fois d'affilée le même outil que le harnais détruisait.
    # Sans borne, il aurait tourné jusqu'à épuiser le contexte.
    extensions_max: int | None = Field(default=0)
    # Garde-fou de sûreté, jamais un budget. Volontairement très au-dessus de ce qu'une tâche
    # réelle demande : l'atteindre signale une boucle, pas une tâche longue.
    tours_absolus_max: int = Field(default=200, ge=1, le=1000)
    # Relancer un tour qui n'a produit ni appel ni réponse lisible. Distinct de la relance sur
    # promesse : celle-ci cherche une annonce, celle-là cherche l'absence de tout.
    relance_sur_tour_muet: bool = False
    relances_muettes_max: int = Field(default=1, ge=0, le=3)
    # 0 désactive la détection de radotage textuel.
    radotage_tours: int = Field(default=0, ge=0, le=5)


# Six tours et un couperet : la conduite d'origine. Conservée telle quelle pour pouvoir mesurer
# ce que la seconde change.
ECHOHUB = Harnais(nom="echohub", tours_outils_max=6)

FORGE = Harnais(
    nom="forge",
    tours_outils_max=10,
    extensions_max=None,
    relance_sur_tour_muet=True,
    relances_muettes_max=2,
    radotage_tours=RADOTAGE_TOURS,
)

_CONNUS: dict[str, Harnais] = {ECHOHUB.nom: ECHOHUB, FORGE.nom: FORGE}
DEFAUT = FORGE

# Mode projet : le 35B a besoin de 2 à 3 relances avant presque chaque appel (mesuré le 2026-10-01) ;
# à 3, la quatrième annonce consécutive clôturait le travail. Le quota se réarme à chaque appel joué.
RELANCES_PROMESSE_PROJET_MAX = 6


def quota_promesse(etat: EtatBoucle) -> int:
    return RELANCES_PROMESSE_PROJET_MAX if etat.mode_projet else RELANCES_PROMESSE_MAX


def fin_de_projet_prematuree(texte: str, etat: EtatBoucle) -> bool:
    """En mode projet, après du travail réel, un texte court sans appel est une pause, pas une fin."""
    return etat.mode_projet and _a_travaille(etat) and pause_sans_bilan(texte)


def _a_travaille(etat: EtatBoucle) -> bool:
    """Un appel a été joué, réussi OU échoué : « Laissez-moi les retrouver. » après un chemin
    introuvable (2026-10-01) est une pause, pas une fin."""
    return etat.aboutis > 0 or bool(etat.echecs_vus)


CONSIGNE_TOUR_MUET = (
    "Your last turn produced nothing: no tool call, and no answer to the user — only reasoning, "
    "which the user does not see. Answer NOW, in French, with what you have. If you need a tool, "
    "call it in this turn with every argument inline."
)

CONSIGNE_RADOTAGE = (
    "You have just written the same thing twice in a row. Repeating it a third time will not help "
    "the user. Either do something different — call a tool, ask a precise question — or say "
    "plainly what is blocking you and stop."
)


def choisir(nom: str | None) -> Harnais:
    """Harnais nommé, ou le défaut. Un nom inconnu retombe sur le défaut plutôt que d'échouer.

    La valeur vient d'une requête HTTP, donc d'une entrée non fiable — et, quand une conversation
    est rejouée, d'un enregistrement écrit par une version antérieure qui pouvait connaître un nom
    disparu depuis. Refuser la génération pour un nom de conduite serait une panne là où il y a une
    valeur par défaut parfaitement valable.
    """
    if not nom:
        return DEFAUT
    return _CONNUS.get(nom.strip().lower(), DEFAUT)


def noms_connus() -> list[str]:
    """Conduites proposables à l'interface, dans l'ordre : le défaut d'abord."""
    return [DEFAUT.nom] + [nom for nom in _CONNUS if nom != DEFAUT.nom]


def tour_muet(texte: str, harnais: Harnais) -> bool:
    """Ce tour n'a-t-il produit aucune réponse lisible ?

    Appelée seulement quand le tour n'a demandé AUCUN outil : un tour qui appelle un outil n'a pas
    à répondre, son travail est l'appel. Confondre les deux relançait des tours parfaitement
    normaux — mesuré le 2026-08-25, deux corrections successives avant d'arriver à ce critère.
    """
    if not harnais.relance_sur_tour_muet:
        return False
    return len(texte.strip()) < MIN_REPONSE_CARACTERES


def _normaliser(texte: str) -> str:
    return _NORMALISATION.sub(" ", visible(texte).lower())



def radote(tours_precedents: list[str], harnais: Harnais) -> bool:
    """Les derniers tours répètent-ils le même texte ?

    `tours_precedents` porte les textes rendus, le plus récent en dernier. La comparaison se fait
    sur la forme normalisée : un radotage reproduit la phrase, pas nécessairement les espaces.
    Un tour vide ne compte jamais comme une répétition — c'est `tour_muet` qui le traite, et deux
    tours vides seraient sinon comptés comme un radotage, avec la mauvaise consigne à la clé.
    """
    seuil = harnais.radotage_tours
    if seuil < 2 or len(tours_precedents) < seuil:
        return False
    derniers = [_normaliser(texte) for texte in tours_precedents[-seuil:]]
    if not derniers[-1]:
        return False
    return all(texte == derniers[-1] for texte in derniers)


@dataclass
class EtatBoucle:
    """État d'un tour de boucle. Porté par l'appel, jamais par le module : deux conversations
    simultanées n'ont rien à partager, et une variable de module les mélangerait silencieusement."""

    harnais: Harnais
    outils_declares: list[dict[str, Any]] | None
    echecs_vus: set[str] = field(default_factory=set)
    # Cumule sur TOUS les tours : un fichier écrit au premier reste écrit même si les suivants
    # échouent.
    aboutis: int = 0
    # Toutes causes confondues : c'est ce compteur que borne la garde globale.
    relances: int = 0
    # Relances dues à une PROMESSE, comptées à part. Confondues avec les autres, deux tours muets
    # épuisaient à eux seuls le quota de promesses, et une annonce arrivant ensuite n'était plus
    # relancée du tout — un modèle bavard perdait sa protection avant même d'avoir annoncé quoi que
    # ce soit. Constaté en test, sur un stub qui commençait par un tour muet.
    relances_promesse: int = 0
    tours_muets: int = 0
    # Tours d'outils consécutifs consommés, et prolongations déjà accordées.
    tours_faits: int = 0
    extensions: int = 0
    # Le modèle a-t-il été averti pour le budget courant ? Remis à faux à chaque extension, pour
    # qu'il soit averti de nouveau avant la borne suivante.
    averti: bool = False
    # Textes des tours ayant appelé un outil, pour la détection de radotage.
    textes: list[str] = field(default_factory=list)
    # Le dernier tour s'est achevé sur une annonce alors qu'il ne reste plus de relance. La boucle
    # doit CLÔTURER au lieu de rendre la main : sans ce drapeau, l'utilisateur reste devant une
    # phrase qui se termine par deux-points et rien derrière.
    promesse_en_suspens: bool = False
    # Mode projet : la conversation construit une application dans un dossier confié. Un tour sans
    # appel n'y est une fin que s'il porte un vrai bilan (voir `fin_de_projet_prematuree`).
    mode_projet: bool = False
    # Relances sur un bilan qui rend à l'utilisateur un reste faisable : jamais réarmées.
    relances_reste: int = 0
    # Mode projet : cité dans les relances, pour qu'elles nomment l'appel à faire.
    dernier_appel: DernierAppel | None = None
    # Tâches ouvertes de `suivre_taches`, lues après chaque appel de l'outil PENDANT cette génération
    # (`None` = la liste n'a pas été tenue ici). Voir `suivi_taches`.
    taches_ouvertes: list[str] | None = None
    relances_taches: int = 0
    ouvertes_a_la_relance: int | None = None


def harnais_demande(options: OptionsGeneration) -> str | None:
    """Conduite demandée par l'appelant, si le contrat en porte une.

    Lu par `getattr` plutôt que par un champ déclaré : `OptionsGeneration` appartient au contrat des
    moteurs, et une conduite de harnais n'est pas un réglage d'échantillonnage. Tant qu'aucune
    interface ne la choisit, l'absence du champ est le cas normal, pas une anomalie.
    """
    valeur = getattr(options, "harnais", None)
    return valeur if isinstance(valeur, str) else None


def rearmer_relances(etat: EtatBoucle) -> None:
    """Un appel d'outil vient d'être joué : les relances ont servi, leur quota se réarme.

    Le quota était consommé sur TOUTE la génération : un modèle qui annonce avant chaque étape (le
    35B en mode projet, mesuré le 2026-10-01) épuisait ses trois relances en trois étapes réussies,
    et la quatrième annonce clôturait un travail en plein élan. Le quota borne l'annonce SANS appel ;
    une annonce suivie d'un appel est du progrès. La boucle reste bornée par `tours_absolus_max`.
    """
    etat.relances = 0
    etat.relances_promesse = 0
    etat.tours_muets = 0


def consigne_de_relance(texte: str, etat: EtatBoucle, avec_outils: bool) -> str | None:
    """Consigne à renvoyer au modèle quand un tour n'a demandé AUCUN outil, ou `None` pour finir.

    Trois cas, dans cet ordre — le premier qui s'applique gagne :

    1. le tour est MUET (ni appel, ni réponse lisible) : le modèle n'a produit que du raisonnement,
       que l'utilisateur ne voit pas. `promesse_non_tenue` écarte ce cas par construction, puisqu'elle
       cherche une annonce et qu'un tour vide n'annonce rien ;
    2. le tour RADOTE : le même texte réécrit, sans qu'aucun outil ne soit appelé entre-temps.
       L'anti-redite d'origine ne borne que les APPELS échoués et ne voit pas ce cas ;
    3. le tour s'achève sur une PROMESSE que rien ne vient tenir — le mécanisme d'origine, intact.

    `None` signifie « la réponse est finie » : c'est le cas courant, et il ne coûte rien.
    """
    if not avec_outils:
        return None
    # Garde globale : somme des trois quotas. Elle borne la boucle sans amputer aucune cause de son
    # budget propre — c'était le défaut du compteur unique.
    if etat.relances >= quota_promesse(etat) + etat.harnais.relances_muettes_max + etat.harnais.radotage_tours:
        return None
    if tour_muet(texte, etat.harnais) and etat.tours_muets < etat.harnais.relances_muettes_max:
        etat.tours_muets += 1
        etat.relances += 1
        logger.warning("Tour muet ({} car.) : relance {}.", len(texte.strip()), etat.relances)
        return CONSIGNE_TOUR_MUET + (rappel_dernier_appel(etat.dernier_appel) if etat.mode_projet else "")
    etat.textes.append(texte)
    if radote(etat.textes, etat.harnais):
        etat.relances += 1
        logger.warning("Texte répété à l'identique sur {} tours : relance {}.",
                       etat.harnais.radotage_tours, etat.relances)
        return CONSIGNE_RADOTAGE + (rappel_dernier_appel(etat.dernier_appel) if etat.mode_projet else "")
    if promesse_non_tenue(texte) or (etat.mode_projet and _a_travaille(etat) and finit_sur_futur_proche(texte)):
        return _relance_promesse(etat)
    return _relance_fin(texte, etat)


def _relance_fin(texte: str, etat: EtatBoucle) -> str | None:
    """Ni muet, ni redite, ni promesse : fin de projet prématurée d'abord, puis tâches ouvertes."""
    consigne = _relance_projet(texte, etat)
    if consigne is None:
        consigne = relance_taches(etat)
        etat.relances += 1 if consigne is not None else 0
    return consigne


def _relance_projet(texte: str, etat: EtatBoucle) -> str | None:
    """Mode projet : une pause sans bilan, ou un bilan qui rend un reste faisable, est relancé."""
    if fin_de_projet_prematuree(texte, etat):
        if etat.relances_promesse >= quota_promesse(etat):
            return None
        etat.relances += 1
        etat.relances_promesse += 1
        logger.warning("Mode projet : pause sans bilan ({} car.) : relance {}/{}.",
                       len(texte.strip()), etat.relances_promesse, quota_promesse(etat))
        return CONSIGNE_SUITE_PROJET + rappel_dernier_appel(etat.dernier_appel)
    if not etat.mode_projet or not _a_travaille(etat) or etat.relances_reste >= RELANCES_RESTE_MAX:
        return None
    consigne = (CONSIGNE_CODE_MONTRE if code_montre(texte)
                else CONSIGNE_RESTE_FAISABLE if reste_faisable(texte) else None)
    if consigne is None:
        return None
    etat.relances += 1
    etat.relances_reste += 1
    logger.warning("Mode projet : fin sur du travail rendu au lieu de fait : relance {}/{}.",
                   etat.relances_reste, RELANCES_RESTE_MAX)
    return consigne + rappel_dernier_appel(etat.dernier_appel)


def _relance_promesse(etat: EtatBoucle) -> str | None:
    """Annonce non tenue : relance escaladée, ou clôture forcée quand le quota est épuisé."""
    if etat.relances_promesse >= quota_promesse(etat):
        # Plus de relance possible, mais le texte reste une promesse : rendre la main ici
        # laisserait l'utilisateur devant une phrase en suspens. `etat.promesse_en_suspens`
        # dit à la boucle de CLÔTURER — un tour sans outil qui doit produire une vraie réponse.
        etat.promesse_en_suspens = True
        logger.warning("Annonce non tenue après {} relance(s) : clôture forcée.", etat.relances_promesse)
        return None
    etat.relances += 1
    etat.relances_promesse += 1
    logger.warning("Réponse close sur une annonce sans appel : relance {}/{}.",
                   etat.relances_promesse, quota_promesse(etat))
    rappel = rappel_dernier_appel(etat.dernier_appel) if etat.mode_projet else ""
    return consigne_promesse(etat.relances_promesse) + rappel


def relancer(messages: list[MessageChat], texte: str, consigne: str) -> list[MessageChat]:
    """Conversation à repasser au moteur pour qu'il reprenne, consigne en dernier tour utilisateur."""
    return list(messages) + [
        MessageChat(role="assistant", content=_sans_appels_outils(texte)),
        MessageChat(role="user", content=consigne),
    ]


__all__ = [
    "CONSIGNE_AVERTISSEMENT",
    "CONSIGNE_DERNIER_TOUR",
    "CONSIGNE_RADOTAGE",
    "EtatBoucle",
    "avertissement_du_tour",
    "budget_epuise",
    "prolonger",
    "consigne_de_relance",
    "harnais_demande",
    "relancer",
    "CONSIGNE_TOUR_MUET",
    "DEFAUT",
    "rearmer_relances",
    "ECHOHUB",
    "FORGE",
    "Harnais",
    "choisir",
    "noms_connus",
    "radote",
    "tour_muet",
]
