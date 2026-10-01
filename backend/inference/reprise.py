"""Reprise d'une réponse que le moteur a coupée avant qu'elle soit complète.

Extrait de `backend/inference/__init__.py` : ces constantes et leur justification y avaient fait
dépasser le module. Elles ne décident de rien — c'est `MoteurChat._diffuser_complet` qui reprend —
mais elles portent la mesure qui a motivé le mécanisme, et elles se lisent mieux ensemble.
"""

from __future__ import annotations

import re

# Reprise d'une réponse coupée par la fenêtre du moteur.
#
# MESURÉ le 2026-08-16 : sur un contexte de 2 048, le moteur rend 1 980 tokens puis
# `finish_reason = "length"`. L'adaptateur le SAIT — il pose la raison sur son morceau de fin — mais
# personne ne la lisait : la chaîne ne rendait que `texte`, `tokens_generes` et `tokens_par_seconde`.
# La réponse s'arrêtait donc en plein milieu d'une phrase, sans que rien ne le signale. Et quand la
# coupure tombait au milieu d'un `<tool_call>`, le JSON devenait illisible, aucun appel n'était
# détecté, et le balisage restait dans la réponse.
#
# Une réponse ne doit JAMAIS s'arrêter avant d'être complète : tant que le moteur dit l'avoir coupée
# par manque de place, on la reprend là où elle s'est arrêtée.
CONTINUATIONS_MAX = 4

# En dessous de ce nombre de tokens libres, reprendre ne produirait rien : `create_chat_completion`
# calcule son plafond à `n_ctx - taille du prompt`, et le prompt de la reprise contient déjà tout ce
# qui a été écrit. On le dit alors clairement, au lieu de boucler sur des tours vides.
MARGE_CONTINUATION_TOKENS = 256

# Rédigée en anglais comme le socle, et pour la même raison mesurée : ces modèles suivent mieux une
# consigne de forme dans la langue de leur raisonnement. Elle n'entre jamais dans l'affichage.
CONSIGNE_REPRISE = (
    "Your previous message was cut off mid-way because the output limit was reached. Continue it "
    "from exactly where it stopped — mid-sentence, even mid-word if that is where it ended. Do not "
    "repeat anything already written, do not restart, do not summarise, do not apologise. Write "
    "only the continuation."
)

# Dit à l'UTILISATEUR, dans le fil, quand la fenêtre est réellement pleine. Une remédiation qui
# existe : le contexte se choisit au chargement du modèle. Laisser une phrase coupée net sans un mot
# serait exactement le défaut corrigé ici.
AVERTISSEMENT_FENETRE_PLEINE = (
    "\n\n*[Réponse interrompue : la fenêtre de contexte du modèle est pleine. "
    "Recharger le modèle avec un contexte plus grand, ou repartir d'une nouvelle conversation.]*"
)


# Relance d'une réponse qui s'ARRÊTE SUR UNE PROMESSE.
#
# Symptôme mesuré le 2026-08-16, socle renforcé déjà en place : le modèle cherche sur le web, cite
# ses sources correctement, puis termine par « Je te l'ai intégré dans le simulateur. Voici le
# fichier : » — et rien. Aucun appel d'outil dans ce tour, donc aucun fichier. La consigne du socle
# (« annoncer et faire sont deux actes distincts ») n'a pas suffi : un modèle quantisé bas annonce
# plus volontiers qu'il n'agit.
#
# Le harnais ne peut pas deviner une intention, mais il peut reconnaître une phrase LAISSÉE OUVERTE.
# Un texte qui se termine sur un deux-points, ou sur une annonce explicite suivie de rien, est le
# seul cas où l'on relance — une seule fois, avec les outils sous les yeux et une consigne directe.
#
# C'est une heuristique, et elle est volontairement étroite : mieux vaut rater une promesse que
# relancer une réponse terminée. Un tour de plus coûte du temps à l'utilisateur.
#
# PORTÉ DE 1 À 3 le 2026-08-26, sur trace de production. Le journal montre la relance partir
# (`POST /v1/chat/completions 200 OK`), le modèle RÉ-ANNONCER, puis la boucle rendre la main —
# `etat.relances` valait déjà 1, donc `promesse_non_tenue` n'était même plus consultée. Ce que
# l'utilisateur lisait à l'écran n'était pas la première annonce mais la seconde, et la conversation
# s'arrêtait là : « Je vais créer les fichiers assembleur […] puis uploader le tout : », fin.
#
# Une seule relance suffit quand le modèle a juste oublié d'agir. Elle ne suffit pas quand il est
# entré dans un mode où il commente son travail au lieu de le faire — état d'autant plus fréquent
# que la quantification est basse (mesuré sur un IQ2_XXS). Trois rappels ESCALADÉS y répondent ;
# trois fois le même n'y répondrait pas, et c'est bien ce qui se passait.
RELANCES_PROMESSE_MAX = 3

# Détection d'une ANNONCE laissée sans suite.
#
# La version d'origine listait douze phrases exactes. Mesuré le 2026-08-26 sur un cas réel : à
# « Je crée une landing page complète avec des illustrations SVG intégrées. », elle rendait `False`
# et aucune relance n'était déclenchée — le modèle s'arrêtait là, la page n'existait pas, et
# l'utilisateur voyait une promesse pour seule réponse. « je crée » n'était pas dans la liste.
#
# Une liste de formulations ne peut pas tenir : demain ce sera « je génère », « je te prépare »,
# « on va faire ». Le critère porte donc sur la FORME de l'annonce — un pronom d'action suivi d'un
# verbe de production — et non sur des phrases apprises une à une.
#
# Volontairement ancré en FIN de message : une annonce en milieu de texte est un commentaire de
# travail normal (« je crée le fichier, puis je le teste ») et la relancer serait du bruit. C'est
# celle qui CLÔT le tour qui pose problème, parce qu'aucun appel ne la suit.
_VERBES_PRODUCTION = (
    "cré|créé|creer|crée|génèr|génér|genere|écri|ecri|rédig|redig|prépar|prepar|constru|"
    "constitu|réalis|realis|produi|fabriqu|dessin|compos|monte|mets en place|mets au point|"
    # Verbes d'EXÉCUTION, ajoutés le 2026-08-26. Produire n'est pas le seul acte qu'un modèle
    # annonce sans le faire : « je lance le script », « je téléverse le fichier » laissent tout
    # autant l'utilisateur devant rien. Ils ne sont pas plus risqués que les autres — la détection
    # reste ancrée en FIN de message, là où plus aucun appel ne peut suivre.
    "lanc|exécut|execut|éxecut|run |upload|télévers|televers|envoi|déploi|deploi|compil|"
    "implémente|implemente|ajoute|complète|complete|corrige|write|create|generate|build|make|"
    "prepare|draft|implement|"
    # Verbes d'INSPECTION et de mise en route, ajoutés le 2026-10-01 : en mode projet, le 35B clôt
    # ses tours sur « Je lis le code actuel pour savoir comment le corriger. » — une annonce au
    # présent que rien ne suit. Toujours ancrée en fin de message.
    "lis |lir|regard|vérifi|verifi|examin|inspect|install|démarr|demarr|teste|check|read|look|inspect|"
    # Verbes de MODIFICATION, ajoutés le 2026-10-01 : « Je vais appeler explicitement `init_db()` au
    # début de chaque route API. » a clos un tour sans relance.
    "appel|modifi|remplac|réécri|reecri|supprim|déplac|deplac|call |replace |modify |update |fix "
)
_ANNONCE = re.compile(
    r"\b(?:je|j'|on|nous|i|we|let me)\s*(?:vais|vas|allons|va|will|am going to|'m going to)?\s*"
    r"\s*(?:now|maintenant)?\s*(?:le|la|les|te|vous|lui|it|you|the)?\s*"
    rf"(?:{_VERBES_PRODUCTION})",
    re.IGNORECASE,
)

# Impératif de la première personne du pluriel, sans pronom : « Corrigeons tout et créons la page
# manquante. » a clos un tour de travail le 2026-10-01 sans qu'aucune relance ne parte — le motif
# ci-dessus exige un sujet (« je », « on », « nous »). Ancré en début de phrase de la dernière ligne.
_IMPERATIF_PLURIEL = re.compile(
    r"(?:^|[.!:,—–-]\s*)(?:maintenant,?\s*|puis\s*|ensuite,?\s*)?"
    r"(?:corrig|cré|cre|lan[cç]|install|v[ée]rifi|test|écriv|ecriv|ajout|démarr|demarr|exécut|execut|"
    r"pass|commen[cç]|mett|construis|compil|relan[cç]|refais|réécriv|reecriv|implément|implement)\w*ons\b",
    re.IGNORECASE,
)

# Conservés tels quels : ce sont des annonces qui ne portent pas de verbe d'action, et que le motif
# ci-dessus ne peut donc pas voir.
_FINS_DE_PROMESSE = (
    "voici le fichier", "voici la nouvelle version", "voici le nouveau", "voici la version",
    "here is the file", "here is the new version", "let me write",
)

# Trois consignes, et le fait qu'elles DIFFÈRENT est le correctif.
#
# Répéter le même rappel dans un contexte qui contient déjà l'annonce et son rappel, c'est demander
# au modèle de faire à l'identique ce qu'il vient de ne pas faire. Chaque rang retire donc une
# option : le premier rappelle la règle, le deuxième interdit la phrase d'introduction — celle qui
# se termine par deux-points et n'appelle rien —, le troisième ferme la sortie « je vais » en ne
# laissant que deux issues, l'appel ou l'aveu.
CONSIGNES_PROMESSE = (
    "Your message ended by announcing something you did not do: no tool call followed it, so "
    "nothing was created and the user sees nothing. Do it NOW, in this turn — emit the call with "
    "every argument inline. If you cannot do it, say plainly what is blocking you, instead of "
    "announcing it a second time.",
    "You announced it again instead of doing it. Stop writing introductions. This turn must START "
    "with the tool call itself — no sentence before it, no colon, no plan. If the tool is not the "
    "right one, call a different one. Announcing a third time produces nothing for the user.",
    "This is the last rappel. Two outcomes are acceptable now, and only two: either this turn "
    "contains a tool call, or it states — in plain words, to the user — what you were unable to do "
    "and why. Do not describe what you are about to do. There is no next turn to do it in.",
)

# Conservé : d'autres modules l'importent, et c'est le premier rang.
CONSIGNE_PROMESSE = CONSIGNES_PROMESSE[0]


# Dernier tour, sans outil déclaré : le modèle NE PEUT PLUS annoncer une action, il ne lui reste
# que la parole. C'est ce qui fait la différence avec une quatrième relance — on ne lui redemande
# pas d'agir, on lui demande de rendre compte.
CONSIGNE_CLOTURE_PROMESSE = (
    "You are out of turns, and no tool is available in this one. Everything you announced and did "
    "not do will not happen. Write the user a real answer now: what you actually accomplished, "
    "what you did not, and — if it is useful to them — the content itself, written out here in "
    "your message. Do not announce anything further."
)


def consigne_promesse(rang: int) -> str:
    """Consigne du rang demandé (1 = première relance), la dernière valant pour tout dépassement."""
    return CONSIGNES_PROMESSE[min(max(1, rang), len(CONSIGNES_PROMESSE)) - 1]


# Marques d'un code NON TERMINÉ, livré comme s'il l'était.
#
# Mesuré le 2026-08-26 : à « upload par api http sur GoFile », le modèle a écrit un bloc Python
# se terminant par `headers={"Authorization": "Bearer YOUR_TOKEN"}` puis `# Now run it`, et a rendu
# la main. Rien n'a tourné, rien n'a été téléversé, et l'utilisateur a lu ça comme une coupure en
# pleine génération — `interrompu` valait pourtant False, 1281 tokens à 22,7 tok/s, contexte à
# 9 867 sur 131 072. Le modèle avait bel et bien fini son tour.
#
# La détection d'annonce ne pouvait pas le voir : elle lit la DERNIÈRE LIGNE, et la dernière ligne
# était la clôture du bloc de code. D'où les deux corrections ci-dessous — remonter à la dernière
# ligne signifiante, et reconnaître un code à trous.
#
# Un jeton laissé en placeholder n'est pas un détail de style : c'est la preuve que le code n'a
# jamais été exécuté, puisqu'il ne PEUT pas l'être. Le relancer sur cette base ne repose sur aucune
# interprétation de l'intention.
_PLACEHOLDERS = re.compile(
    r"YOUR[_-]?(TOKEN|API[_-]?KEY|KEY|SECRET|PASSWORD|ID)|<your[_ -]|"
    r"\bREPLACE[_ -]?(ME|WITH)\b|\bINSERT[_ -]?YOUR\b|\bTODO\b|\bFIXME\b|"
    r"xxxxx|<API[_-]?KEY>|\{\{[a-z_]+\}\}",
    re.IGNORECASE,
)

# Clôture d'un bloc de code Markdown en fin de message.
_BLOC_CODE_FINAL = re.compile(r"```(?P<langue>[a-zA-Z0-9_+-]*)\n(?P<code>.*?)\n?```\s*$", re.DOTALL)

# Bloc shell final introduit par deux-points : « Je lance l'installation en une seule commande :
# ```bash …``` » — la commande est MONTRÉE au lieu d'être exécutée (35B, mode projet, 2026-10-01).
# Sauf quand l'introduction s'adresse à l'utilisateur (« Pour lancer l'app : ») : c'est un mode
# d'emploi, la fin normale d'un bilan.
_LANGUES_SHELL = frozenset({"", "bash", "sh", "shell", "zsh", "console"})
_MODE_D_EMPLOI = re.compile(
    r"\b(?:pour \w+|to (?:run|start|install|use|test|build|compile)|usage|utilise[sz]?|"
    r"vous pouvez|tu peux)\b", re.IGNORECASE)


def _commande_montree(bloc: re.Match[str], fin: str) -> bool:
    if bloc.group("langue").lower() not in _LANGUES_SHELL:
        return False
    intro = fin[: bloc.start()].rstrip()
    derniere = intro.rsplit("\n", 1)[-1]
    if not intro:
        return True  # un message réduit à un bloc shell n'est jamais un bilan : c'est un appel montré
    if _MODE_D_EMPLOI.search(derniere) is not None:
        return False
    return (intro.endswith(":") or _ANNONCE.search(derniere) is not None
            or _IMPERATIF_PLURIEL.search(derniere) is not None)


def _nomme_un_outil(code: str) -> bool:
    """Le bloc final nomme-t-il un outil enregistré ? C'est alors un appel ÉCRIT au lieu d'être émis.

    Mesuré le 2026-10-01 : « ```bash executer_commande commande="pwd" ``` » a clos un tour du mode
    projet. Le nom vient du registre, pas d'une liste tenue ici : un outil ajouté y est vu d'office.
    Import local — `outils` charge le chat, qui charge l'inférence.
    """
    try:
        from backend.outils import disponibles

        noms = {outil.nom for outil in disponibles()}
    except Exception:  # noqa: BLE001 — sans registre lisible, la détection se tait
        return False
    return any(re.search(rf"\b{re.escape(nom)}\b", code) for nom in noms)


def promesse_non_tenue(texte: str) -> bool:
    """Le tour s'achève-t-il sur une annonce laissée sans suite ?

    Appelée seulement quand le tour n'a produit AUCUN appel d'outil : sans cette condition, un
    modèle qui annonce puis appelle — le comportement normal — serait relancé pour rien.
    """
    fin = texte.rstrip()
    if not fin:
        return False

    bloc = _BLOC_CODE_FINAL.search(fin)
    if bloc is not None:
        # Un code à trous n'est pas un livrable : il ne peut pas avoir tourné.
        if _PLACEHOLDERS.search(bloc.group("code")) or _nomme_un_outil(bloc.group("code")):
            return True
        if _commande_montree(bloc, fin):
            return True
        # La clôture du bloc masquait la vraie fin du message. On regarde ce qui la précède —
        # commentaire impératif, phrase d'annonce — au lieu de trois backticks qui n'annoncent rien.
        fin = (fin[: bloc.start()] + "\n" + bloc.group("code")).rstrip() or fin

    if fin.endswith(":"):
        return True
    derniere_ligne = fin.rsplit("\n", 1)[-1]
    # Le commentaire de tête est retiré : « # Now run it » est une annonce, le croisillon n'y change
    # rien. C'est la seule concession faite au fait que la ligne vienne d'un bloc de code.
    derniere_ligne = derniere_ligne.lstrip("#/ \t")
    if any(marqueur in derniere_ligne.lower() for marqueur in _FINS_DE_PROMESSE):
        return True
    return _ANNONCE.search(derniere_ligne) is not None or _IMPERATIF_PLURIEL.search(derniere_ligne) is not None
