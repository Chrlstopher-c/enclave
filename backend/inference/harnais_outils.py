"""Mise en forme du flux d'outils — balises affichées, aperçus, et ce qui repart au moteur.

Extrait de `backend/inference/__init__.py` le 2026-08-16 : ces règles de mise en forme y avaient
grossi jusqu'à faire dépasser le module, alors qu'elles forment une unité cohérente et testable
seule. Elles ne décident de rien — ni quand appeler un outil, ni lequel : elles décrivent COMMENT
ce qui a été fait est montré à l'utilisateur, et sous quelle forme réduite il revient au modèle.

Une distinction gouverne tout le fichier, et l'oublier a coûté cher deux fois :

- ce que l'utilisateur VOIT est intégral. Le message enregistré n'est jamais touché ;
- ce qui repart AU MOTEUR est réduit — blocs d'outils compactés, balisage d'appel retiré. C'est une
  économie de contexte et une hygiène de prompt, jamais une perte d'information : tout reste
  consultable à l'écran, et un fichier reste relisible à la demande.
"""

from __future__ import annotations

import re

"""Balises du flux annonçant un outil. Elles voyagent dans le texte de la réponse, comme celles du
raisonnement, et l'interface les replie de la même façon : l'utilisateur voit la recherche se
faire, sans que le résultat brut n'écrase la réponse.

Passer par le texte plutôt que par un type d'événement dédié n'est pas un raccourci : c'est ce qui
rend l'information PERSISTANTE. Un événement de flux disparaît au rechargement de la page, alors
qu'un message enregistré garde la trace de ce qui a été cherché — et c'est justement ce qui permet
de vérifier une réponse plus tard."""
BALISE_OUTIL_OUVRANTE = "<outil>"
BALISE_OUTIL_FERMANTE = "</outil>"

# Le bloc porte deux parties distinctes : ce que le modèle a DEMANDÉ, puis ce que l'outil a RENDU.
# Les séparer n'est pas cosmétique — juger une réponse suppose de voir la requête qui l'a produite,
# et une recherche mal formulée explique souvent un résultat hors sujet. L'entrée part avant
# l'exécution, la sortie après : l'utilisateur voit donc la demande pendant que l'outil travaille.
BALISE_ENTREE_OUVRANTE = "<entree>"
BALISE_ENTREE_FERMANTE = "</entree>"
BALISE_SORTIE_OUVRANTE = "<sortie>"
BALISE_SORTIE_FERMANTE = "</sortie>"

# Variante portant l'ISSUE de l'appel. Ajoutée le 2026-08-26 : jusque-là, l'interface DEVINAIT
# l'échec en reconnaissant des préfixes dans le texte du résultat (« Échec de l'outil : », « Failed:
# »). Une lecture par préfixe tient jusqu'au premier message reformulé, traduit, ou remplacé par un
# `EchecOutil` au texte libre — et un outil raté s'affichait alors « terminé ».
#
# L'issue est un FAIT connu du harnais au moment où il écrit la balise : la transporter coûte douze
# caractères et supprime toute interprétation en aval.
#
# La forme sans attribut reste émise pour un succès : elle est déjà dans tous les messages
# enregistrés, et un historique relu ne doit pas changer d'apparence parce que le format a évolué.
BALISE_SORTIE_ECHEC = '<sortie etat="echec">'

# Marqueur de fin d'étape, posé quand le tour qui vient de s'achever a demandé un outil.
#
# Un modèle commente son travail avant d'appeler : « je vais chercher », « j'ai obtenu 6 résultats,
# je synthétise ». Ce commentaire n'est pas la réponse, et le laisser dans le flux le fait passer
# pour telle — parfois affiché en clair, parfois avalé dans un bloc de raisonnement selon que le
# modèle a balisé ou non. Le même contenu changeait donc de traitement d'un tour à l'autre.
#
# Le marqueur est posé APRÈS coup plutôt qu'une balise ouverte à l'avance : au début d'un tour, rien
# ne dit encore s'il produira un appel d'outil ou la réponse finale. Ouvrir une balise « au cas où »
# replierait la réponse quand aucun outil n'est demandé — c'est-à-dire la plupart du temps.
# Le streaming reste donc intact : l'utilisateur voit le texte arriver, et il est reclassé une fois
# l'appel connu.
BALISE_FIN_ETAPE = "<etape-fin/>"

# Compaction des blocs d'outils des tours PASSÉS, dans ce qui repart au modèle.
#
# Le contenu d'un outil n'a de valeur pleine que pendant le tour qui l'a demandé : c'est là qu'on
# relit un fichier pour le corriger. Aux tours suivants, seul son EXISTENCE compte encore — savoir
# qu'on a lu `app.py` et à quoi il ressemblait en gros. Garder 200 lignes de fichier dans
# l'historique de chaque tour suivant remplit la fenêtre avec ce que le modèle peut relire à la
# demande, et c'est l'historique de conversation qui en paie le prix.
#
# La compaction ne touche QUE ce qui part au moteur. Le message enregistré et ce que l'utilisateur
# voit à l'écran restent entiers : c'est une économie de contexte, pas une perte d'information.
LIGNES_BLOC_HISTORIQUE = 8

_MOTIF_BLOC_OUTIL = re.compile(
    f"({re.escape(BALISE_ENTREE_OUVRANTE)}|{re.escape(BALISE_SORTIE_OUVRANTE)}"
    f"|{re.escape(BALISE_SORTIE_ECHEC)})"
    r"(?P<corps>.*?)"
    f"({re.escape(BALISE_ENTREE_FERMANTE)}|{re.escape(BALISE_SORTIE_FERMANTE)})",
    re.DOTALL,
)


def _compacter_corps(corps: str) -> str:
    """Garde les premières lignes d'un bloc et DIT ce qui a été retiré, plutôt que de couper net."""
    lignes = corps.splitlines()
    if len(lignes) <= LIGNES_BLOC_HISTORIQUE:
        return corps
    gardees = lignes[:LIGNES_BLOC_HISTORIQUE]
    reste = len(lignes) - len(gardees)
    return "\n".join([*gardees, f"[… {reste} lignes retirées de l'historique — relire le fichier si besoin]"])


def _compacter_blocs_outils(texte: str) -> str:
    """Réduit entrées et sorties d'outils d'un message d'historique. Le reste du texte est intact."""
    if BALISE_OUTIL_OUVRANTE not in texte:
        return texte
    return _MOTIF_BLOC_OUTIL.sub(
        lambda trouve: f"{trouve.group(1)}{_compacter_corps(trouve.group('corps'))}{trouve.group(3)}",
        texte,
    )


# Appels d'outils écrits par le modèle, retirés de ce qui lui REVIENT comme son propre texte.
#
# Le harnais lit ces appels, les exécute, et rend le résultat dans un message de rôle `tool`. Le
# balisage d'origine n'a donc plus aucune fonction une fois le tour terminé — mais il reste dans le
# texte de l'assistant, et le modèle le relit comme un exemple de ce qu'il a « bien » fait.
#
# Mesuré sur la conversation du 2026-08-16 (messages 141, 143 et 145 en base) : après un premier
# appel incomplet, `<function=ecrire_fichier></function>` — vide — se retrouve dans l'historique, et
# le modèle le rejoue à l'identique tour après tour, y compris au PREMIER tour du message suivant,
# où plus rien ne l'y poussait. Un appel raté qu'on lui remontre est un gabarit qu'on lui propose.
#
# C'est la même faute que le préfixe « [outil nom — résultat] » corrigé plus tôt : tout format que
# le harnais laisse dans le contexte finit imité. Ce qu'il a demandé reste visible à l'utilisateur —
# le message ENREGISTRÉ n'est pas touché, comme pour la compaction.
_MOTIF_APPEL_A_RETIRER = re.compile(
    r"<tool_call>.*?(?:</tool_call>|\Z)|<function=[\w.-]+>.*?(?:</function>|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def _sans_appels_outils(texte: str) -> str:
    """Retire le balisage d'appel d'un texte d'assistant qui repart au moteur.

    N'enlève que le balisage : le raisonnement et la prose autour restent entiers, y compris la
    phrase qui annonçait l'appel. Le modèle garde donc le fil de ce qu'il faisait, sans la forme
    exacte qu'il pourrait recopier.
    """
    if "<tool_call>" not in texte and "<function=" not in texte:
        return texte
    return _MOTIF_APPEL_A_RETIRER.sub("", texte)


# Aperçu d'un argument long dans le bloc d'appel affiché. Écrire un fichier passe son contenu
# ENTIER en argument : sans aperçu, le bloc « Appel d'outil » pesait 7 261 caractères pour une page
# HTML (mesuré le 2026-08-16) et l'utilisateur devait le dérouler pour retrouver quoi que ce soit.
# Cinq lignes suffisent à reconnaître ce qui a été écrit ; le fichier lui-même reste consultable en
# artefact, en entier, où il a sa place.
LIGNES_APERCU_ARGUMENT = 5
CARACTERES_APERCU_LIGNE = 160


def _apercu_valeur(valeur: object) -> str:
    """Valeur d'argument ramenée à un aperçu lisible — jamais tronquée en silence."""
    if isinstance(valeur, list) and valeur and all(isinstance(e, dict) and "chemin" in e for e in valeur):
        # `ecrire_fichiers` : les chemins, pas le contenu entier de chaque fichier.
        return " · ".join(str(e["chemin"]) for e in valeur)
    texte = str(valeur)
    lignes = texte.splitlines()
    if len(lignes) <= LIGNES_APERCU_ARGUMENT and len(texte) <= CARACTERES_APERCU_LIGNE:
        return texte
    gardees = [ligne[:CARACTERES_APERCU_LIGNE] for ligne in lignes[:LIGNES_APERCU_ARGUMENT]]
    reste = len(lignes) - len(gardees)
    suite = f"… (+{reste} lignes, {len(texte)} caractères)" if reste > 0 else f"… ({len(texte)} caractères)"
    return "\n".join([*gardees, suite])


def _annonce(nom: str, arguments: object) -> str:
    """Ligne lisible d'un appel, montrée telle quelle dans le bloc replié."""
    if isinstance(arguments, dict):
        detail = ", ".join(f"{cle} : {_apercu_valeur(valeur)}" for cle, valeur in arguments.items())
    else:
        detail = _apercu_valeur(arguments) if arguments else ""
    return f"{nom}({detail})" if detail else nom
