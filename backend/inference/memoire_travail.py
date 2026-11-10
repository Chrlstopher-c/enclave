"""Mémoire de travail : ce que les outils ont rendu reste lisible d'un message de l'utilisateur à l'autre.

Constaté le 2026-11-10 (Chris, modèles 9B) : à chaque « continue », le modèle relisait tous les
fichiers déjà lus, et tournait parfois en boucle dessus. Cause : `pour_le_modele` remplaçait les
blocs d'outils des messages passés par un décompte (« lire_fichier ×3 ») suivi de « leurs sorties
ne sont plus dans le contexte : relancer ou relire si besoin » — le modèle faisait ce qu'on lui
disait.

Deux remèdes :
- `deplier` + `budgeter` : un message d'assistant enregistré redevient la suite qu'il était en cours
  de tour — prose, puis résultat d'outil en rôle `tool` (le canal que le modèle a appris, qu'il
  n'imite pas dans sa prose), etc. Les résultats les plus récents restent entiers dans un budget ;
  au-delà, une ligne précise dit QUEL appel a été fait, sans inviter à le refaire ;
- `redite` + `avis_redite` : un appel dont la sortie est déjà, mot pour mot, dans le contexte n'est
  pas resservi en entier ; le modèle est renvoyé à ce qu'il a déjà, et averti s'il insiste.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.inference.consignes import pour_le_modele as consignes_pour_le_modele
from backend.inference.hygiene_historique import pour_le_modele

# Caractères de sorties d'outils PASSÉES gardées entières (≈ 12 k tokens). Au-delà, les plus
# anciennes sont résumées en une ligne. Le tour en cours n'est pas concerné : `compaction_boucle`.
BUDGET_SORTIES = 48_000
# En dessous, une sortie (« Écrit … », « ok ») ne vaut pas un renvoi : elle est rendue telle quelle.
LONGUEUR_REDITE_MIN = 120
# Redites dans une même génération à partir desquelles l'avis devient une consigne d'arrêt.
REDITES_INSISTANTES = 3
# Redites à partir desquelles le harnais retire les outils et fait conclure (photo de Chris, 2026-11-10 :
# quinze relectures identiques d'une plage au-delà de la fin du fichier, sans fin possible en FORGE).
REDITES_ARRET = 5

CONSIGNE_BOUCLE = (
    "You kept making calls that returned nothing new. Tools are off for this turn. Answer the user "
    "now: what you did, what you found, and what exactly blocks you."
)

_BLOC = re.compile(
    r"<outil>\s*<entree>(?P<entree>.*?)</entree>\s*(?P<ouvrante><sortie[^>]*>)(?P<sortie>.*?)</sortie>\s*</outil>"
    r"|<consigne>(?:id:[^\n]*\n)?(?P<consigne>.*?)</consigne>",
    re.DOTALL,
)


@dataclass
class Segment:
    """Morceau d'un message déplié : prose d'assistant, ou résultat d'un appel."""

    role: str
    contenu: str
    annonce: str = ""
    echec: bool = False


def deplier(texte: str) -> list[Segment]:
    """Message d'assistant enregistré → prose et résultats d'outils, dans l'ordre où ils ont eu lieu.

    Toujours une prose d'assistant en tête (vide au besoin, comme en cours de tour) : un résultat
    d'outil qui suivrait directement le message de l'utilisateur casse plusieurs gabarits.
    """
    segments: list[Segment] = []
    vus: set[str] = set()
    curseur = 0
    for bloc in _BLOC.finditer(texte):
        prose = _sans_redites(pour_le_modele(texte[curseur:bloc.start()]), vus)
        if prose or not segments or (segments[-1].role == "user" and bloc.group("consigne") is None):
            segments.append(Segment("assistant", prose))
        if bloc.group("consigne") is not None:
            # Message glissé par l'utilisateur pendant le travail : rendu à son rôle (`consignes`).
            segments.append(Segment("user", consignes_pour_le_modele(bloc.group("consigne").strip())))
        else:
            segments.append(Segment("tool", bloc.group("sortie").strip(), bloc.group("entree").strip(),
                                    "echec" in bloc.group("ouvrante")))
        curseur = bloc.end()
    fin = _sans_redites(pour_le_modele(texte[curseur:]), vus)
    if fin or not segments:
        segments.append(Segment("assistant", fin))
    return segments


def _sans_redites(prose: str, vus: set[str]) -> str:
    """Paragraphes déjà dits dans ce message retirés : une boucle enregistrée ne doit pas resservir de modèle.

    Mesuré le 2026-11-10 : après une première boucle, CHAQUE message suivant de la conversation bouclait
    aussi — l'historique lui remontrait vingt fois « Je vais corriger l'application… », et il recopiait.
    """
    gardes = []
    for paragraphe in prose.split("\n"):
        cle = " ".join(paragraphe.lower().split())
        if cle and cle in vus:
            continue
        vus.add(cle)
        gardes.append(paragraphe)
    return "\n".join(gardes).strip()


def _resultat(segment: Segment) -> str:
    issue = " (FAILED)" if segment.echec else ""
    return f"Result of {segment.annonce}{issue}:\n{segment.contenu}"


def _retire(segment: Segment) -> str:
    return (f"Result of {segment.annonce}: older output ({len(segment.contenu)} characters) no longer "
            "shown. What you learned from it is in your own messages. Call it again only if you need "
            "its exact content and it may have changed.")


def budgeter(segments: list[Segment], budget: int = BUDGET_SORTIES) -> list[Segment]:
    """Sorties entières des plus récentes aux plus anciennes tant que le budget tient ; ligne au-delà."""
    restant = budget
    rendus: list[Segment] = []
    for segment in reversed(segments):
        if segment.role != "tool":
            rendus.append(segment)
            continue
        garde = len(segment.contenu) <= restant
        restant -= len(segment.contenu) if garde else 0
        rendus.append(Segment("tool", _resultat(segment) if garde else _retire(segment)))
        # Une fois une sortie retirée, toutes les plus anciennes le sont aussi : garder une vieille
        # lecture courte en sautant une récente donnerait au modèle un contexte à trous.
        restant = restant if garde else -1
    return list(reversed(rendus))


def redite(texte: str, contexte: list[object]) -> bool:
    """La sortie est-elle déjà, mot pour mot, dans un résultat d'outil encore présent au contexte ?

    Comparer la sortie elle-même, et non l'appel, est ce qui rend le renvoi VRAI : un fichier modifié
    entre-temps rend un autre texte et repasse en entier, un résultat retiré du contexte aussi.
    """
    if len(texte) < LONGUEUR_REDITE_MIN:
        return False
    for message in contexte:
        contenu = getattr(message, "content", None)
        if getattr(message, "role", None) == "tool" and isinstance(contenu, str) and texte in contenu:
            return True
    return False


def tourne_en_rond(redites: int) -> bool:
    """Assez de redites pour retirer les outils : la boucle ne produira plus rien."""
    return redites >= REDITES_ARRET


def avis_redite(annonce: str, redites: int) -> str:
    """Ce qui remplace une sortie déjà présente au contexte ; ferme à partir de la 3ᵉ redite."""
    avis = (f"Same output as the result of {annonce} already in your context above: nothing changed "
            "since. Not repeated here. Use that result; do not call this again.")
    if redites >= REDITES_INSISTANTES:
        avis += (f" You have now made {redites} calls that returned nothing new. Stop reading: act on "
                 "what you already have (write, edit, run) or answer the user.")
    return avis


__all__ = ["BUDGET_SORTIES", "CONSIGNE_BOUCLE", "Segment", "avis_redite", "budgeter", "deplier", "redite",
           "tourne_en_rond"]
