"""Domaine `inference` — décider d'un plan de chargement, l'appliquer, générer.

Interface publique du domaine. Deux surfaces distinctes, à ne pas confondre :

- le **planificateur** (`planifier`, `degrader`) est pur : il décide à partir de mesures qu'on lui
  donne, ne touche ni GPU ni disque, et se teste sans matériel. C'est ce qui rend ses règles
  vérifiables, contrairement à la v1 où elles étaient dispersées dans le chargeur ;
- le **superviseur** applique : il charge, sonde, génère, décharge.

`creer_moteur_chat` est la fabrique que le domaine `chat` cherche à l'exécution. Elle est ici, et
non dans `chat`, parce que c'est le domaine qui possède le moteur qui doit fournir l'adaptateur —
`chat` ne connaît que la forme qu'il attend (`chat/port_inference.py`), jamais notre implémentation.

Aucun import de `backend.chat` dans ce fichier : la dépendance ne va que dans un sens. La requête
reçue est lue par attributs et le flux rendu sous une forme que `chat.adaptation_inference` sait
normaliser — c'est exactement le point de souplesse que ce module documente.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from backend.inference.engines_adapters import (
    MessageChat,
    OptionsGeneration,
    PartieContenu,
    PartieImageChemin,
    PartieTexte,
    superviseur,
)
# Réexportés : `api.py` et les tests les lisent sur `backend.inference`, qui reste la surface
# publique du domaine. Un découpage interne ne doit pas obliger les appelants à connaître le
# sous-module — même règle que partout ici : on importe le domaine, jamais ses entrailles.
from backend.inference import harnais
from backend.inference.harnais import (
    EtatBoucle,
    avertissement_du_tour,
    budget_epuise,
    consigne_de_relance,
    prolonger,
    relancer,
)
from backend.inference.reprise import CONSIGNE_CLOTURE_PROMESSE
from backend.inference.harnais_outils import (
    BALISE_ENTREE_FERMANTE,
    BALISE_ENTREE_OUVRANTE,
    BALISE_FIN_ETAPE,
    BALISE_OUTIL_FERMANTE,
    BALISE_OUTIL_OUVRANTE,
    BALISE_SORTIE_ECHEC,
    BALISE_SORTIE_FERMANTE,
    BALISE_SORTIE_OUVRANTE,
    CARACTERES_APERCU_LIGNE,
    LIGNES_APERCU_ARGUMENT,
    LIGNES_BLOC_HISTORIQUE,
    _annonce,
    _apercu_valeur,
    _compacter_blocs_outils,
    _compacter_corps,
    _sans_appels_outils,
)
from backend.inference.reprise import (
    AVERTISSEMENT_FENETRE_PLEINE,
    CONSIGNE_PROMESSE,
    CONSIGNE_REPRISE,
    CONTINUATIONS_MAX,
    MARGE_CONTINUATION_TOKENS,
    RELANCES_PROMESSE_MAX,
    promesse_non_tenue,
)
from backend.inference.planner import (
    DemandeDeChargement,
    MetadonneesModele,
    PlanDeChargement,
    PreferencesUtilisateur,
    ProfilMachine,
    degrader,
    planifier,
)


def _options_depuis(parametres: object) -> OptionsGeneration:
    """Traduit les réglages d'une conversation en options moteur.

    Lecture par attributs plutôt qu'import du modèle de `chat` : la traduction est explicite et
    la dépendance reste à sens unique. Un champ absent retombe sur le défaut du moteur, jamais sur
    une valeur inventée ici.
    """

    def champ(nom: str) -> Any:
        return getattr(parametres, nom, None)

    top_k = champ("top_k")
    return OptionsGeneration(
        temperature=champ("temperature") if champ("temperature") is not None else 0.7,
        top_p=champ("top_p") if champ("top_p") is not None else 0.95,
        # `0` signifie « désactivé » côté llama.cpp, alors que le contrat moteur exige `>= 1` ou
        # `None`. Les deux disent la même chose ; on traduit plutôt que de laisser passer un 0
        # qui serait refusé à la validation.
        top_k=top_k if isinstance(top_k, int) and top_k >= 1 else None,
        repetition_penalty=champ("penalite_repetition"),
        max_tokens=champ("max_tokens"),
        stop=list(champ("sequences_arret") or []),
        graine=champ("graine"),
    )


def _messages_depuis(messages: object) -> list[MessageChat]:
    """Convertit les messages de la conversation au format des moteurs (`content`, pas `contenu`).

    Un message sans pièce jointe garde `content` en texte simple — forme inchangée depuis avant ce
    lot. Un message AVEC pièces devient une liste de parties (texte, puis images). Aucune image
    n'est encodée ici : `content` porte encore des CHEMINS disque (`PartieImageChemin`), jamais du
    base64 — c'est l'adaptateur moteur qui encode, au tout dernier moment (plan d'exécution, 2.2.4).

    Les blocs d'outils des tours PASSÉS y sont compactés (`_compacter_blocs_outils`). Ce qui arrive
    ici vient de l'historique, par définition : les résultats du tour EN COURS sont ajoutés plus
    loin, en entier, par la boucle de `MoteurChat._flux`.
    """
    convertis: list[MessageChat] = []
    for message in messages or ():
        role = getattr(message, "role", None)
        contenu = getattr(message, "contenu", None)
        if contenu is None:
            contenu = getattr(message, "content", None)
        if role is None or contenu is None:
            logger.warning("Message ignoré, forme inattendue : {}", type(message).__name__)
            continue
        if isinstance(contenu, str):
            contenu = _compacter_blocs_outils(_sans_appels_outils(contenu))
        pieces = getattr(message, "pieces", None) or ()
        convertis.append(MessageChat(role=role, content=_contenu_moteur(contenu, pieces)))
    return convertis


def _contenu_moteur(contenu: str, pieces: object) -> str | list[PartieContenu]:
    """`content` du contrat moteur : texte simple sans pièce jointe, liste de parties sinon."""
    if not pieces:
        return contenu
    parties: list[PartieContenu] = []
    if contenu:
        parties.append(PartieTexte(text=contenu))
    for piece in pieces:
        chemin = getattr(piece, "chemin", None)
        type_mime = getattr(piece, "type_mime", None)
        if chemin is None or type_mime is None:
            logger.warning("Pièce jointe ignorée, forme inattendue : {}", type(piece).__name__)
            continue
        nom_affiche = getattr(piece, "nom_affiche", None) or ""
        parties.append(PartieImageChemin(chemin=str(chemin), type_mime=type_mime, nom_affiche=nom_affiche))
    return parties if parties else contenu


# Tours d'outils avant de rendre la main au modèle pour de bon.
#
# La boucle de travail que le socle DEMANDE au modèle compte plusieurs appels enchaînés : écrire un
# fichier, l'exécuter, le relire après une erreur, le corriger, le présenter. Cinq appels, donc cinq
# tours. Une borne à trois coupait cette boucle en son milieu.
#
# Les outils restent DÉCLARÉS à chaque tour. Ils ne l'étaient qu'au premier (plan d'exécution,
# L10-b), pour empêcher un modèle de redemander sans fin un outil dont il avait déjà le résultat.
# MESURÉ le 2026-08-16 sur la conversation réelle, contexte servi de 131 072 tokens et seulement
# 18 835 occupés — donc sans la moindre contrainte de fenêtre : le modèle appelle `lire_fichier`,
# apprend que le fichier n'existe pas, annonce « je repars de zéro, voici la nouvelle version »…
# et s'arrête là. Il n'a pas renoncé : au tour suivant, `ecrire_fichier` ne lui était plus déclaré.
# C'est exactement le symptôme rapporté — « ça coupe alors que le contexte est large ».
#
# Ce que L10-b protégeait est désormais couvert, et mieux ciblé : cette borne-ci, l'anti-redite sur
# les appels échoués (`_REDITE`), et le retrait du balisage d'appel de l'historique renvoyé. Retirer
# ses outils au modèle au moment précis où la tâche en réclame un second n'était pas une protection,
# c'était une amputation.
#
# Reste vrai, et c'est la distinction à ne pas perdre : ne plus déclarer un outil n'a jamais voulu
# dire refuser de l'exécuter. La sortie de boucle ne dépend que des appels réellement demandés.
TOURS_OUTILS_MAX = 6


def _prompt_de_reprise(messages: list[MessageChat], recu: list[str]) -> list[MessageChat]:
    """Conversation à repasser au moteur pour qu'il CONTINUE au lieu de recommencer.

    Le partiel devient un tour d'assistant, suivi d'une consigne de reprise. Cette forme marche avec
    tous les gabarits présents, là où un pré-remplissage de tour dépendrait de l'un d'eux — et un
    gabarit qui refermerait le tour d'assistant ferait tout reprendre depuis le début.
    """
    return list(messages) + [
        MessageChat(role="assistant", content="".join(recu)),
        MessageChat(role="user", content=CONSIGNE_REPRISE),
    ]


def _texte_appel(appel: dict[str, Any]) -> tuple[str, Any]:
    """Nom et arguments d'un appel, quelle que soit la forme rendue par le gabarit du modèle."""
    fonction = appel.get("function")
    if isinstance(fonction, dict):
        return str(fonction.get("name", "")), fonction.get("arguments", "")
    return str(appel.get("name", "")), appel.get("arguments", "")


def _appels_demandes(texte: str) -> list[dict[str, Any]]:
    """Appels d'outils repérés dans ce que le modèle vient d'écrire.

    Lus dans le TEXTE reçu, parce que c'est là qu'ils arrivent : avec le gabarit natif d'un GGUF,
    llama-cpp-python ne remplit pas `tool_calls` et le modèle émet `<tool_call>{…}</tool_call>`
    au fil du flux. Le lire ici évite un second appel au moteur — qui construirait un prompt
    différent, perdrait le cache et doublerait le temps avant le premier token.
    """
    from backend.inference.engines_adapters.adaptateur_llama_cpp import _appels_dans_le_texte

    return _appels_dans_le_texte(texte)


def _signature(nom: str, arguments: Any) -> str:
    """Identité d'un appel, pour reconnaître une redite exacte. Jamais montrée au modèle."""
    return f"{nom}\x00{arguments!r}"


# Rendu à la place d'une exécution quand le modèle rejoue un appel qui a DÉJÀ ÉCHOUÉ à l'identique,
# sans que rien n'ait abouti entre-temps. C'est la boucle observée le 2026-08-16 : trois tours
# identiques, puis une réponse annonçant un fichier qui n'existait pas.
#
# Seuls les ÉCHECS sont bornés, et le premier succès efface l'ardoise. Un appel réussi peut
# légitimement se répéter — relire un fichier après l'avoir modifié rend un autre contenu —, et un
# appel échoué peut légitimement réussir au second essai si l'état a changé depuis : `lire_fichier`
# sur un fichier absent, puis `ecrire_fichier`, puis la même lecture. Borner la répétition tout
# court aurait cassé exactement la boucle de travail que ces outils existent pour permettre.
_REDITE = (
    "Failed: this exact call was already made in this turn and gave the same result. "
    "Repeating it changes nothing. Either send it with the arguments that were missing, or stop "
    "calling tools and answer with what you actually have."
)

# Injecté avant le tour de clôture quand AUCUN appel du tour n'a abouti. Sans lui, le modèle
# terminait sur « Voici le nouveau fichier […] vous pouvez l'ouvrir en cliquant sur la carte
# ci-dessus » alors que rien n'avait été écrit et qu'aucune carte n'existait (message 145 en base,
# 2026-08-16). Un harnais qui laisse annoncer un résultat inexistant est pire qu'un harnais qui
# échoue : l'utilisateur ne peut même pas savoir que ça a raté.
_AUCUN_OUTIL_ABOUTI = (
    "None of the tool calls in this turn succeeded: no file was written, read, or shown. "
    "Answer the user now, in French, using only what you actually have. Say plainly that the "
    "operation failed. Do NOT claim a file was created, and do NOT refer to a card or an attachment."
)


def _avec_avertissement(messages: list[MessageChat], etat: EtatBoucle) -> list[MessageChat]:
    """Consomme un tour de budget et injecte l'avertissement s'il est dû.

    L'avertissement PRÉCÈDE le tour : prévenir après coup ne sert à rien, le modèle a déjà décidé
    de ce qu'il faisait de son dernier appel.
    """
    etat.tours_faits += 1
    avis = avertissement_du_tour(etat)
    if avis is None:
        return messages
    return list(messages) + [MessageChat(role="tool", content=avis)]


def _prolonger_si_demande(etat: EtatBoucle) -> None:
    """Prolonge le budget quand le modèle a rappelé un outil APRÈS l'avertissement.

    C'est lui qui décide de continuer, pas le harnais : le harnais l'a prévenu qu'il approchait
    d'une borne, et un nouvel appel est sa réponse.
    """
    if etat.averti or _restants_nuls(etat):
        prolonger(etat)


def _restants_nuls(etat: EtatBoucle) -> bool:
    """Le budget courant est-il consommé, alors qu'une extension reste possible ?"""
    accorde = etat.harnais.tours_outils_max * (1 + etat.extensions)
    plafond = etat.harnais.extensions_max
    # `None` = prolongations illimitées (harnais FORGE) : comparer à None levait TypeError au
    # dixième tour d'outils, et tuait exactement les longues tâches que ce harnais doit permettre.
    return etat.tours_faits >= accorde and (plafond is None or etat.extensions < plafond)


def _bloc_sortie(texte: str, succes: bool) -> str:
    """Sortie d'un appel, portant son ISSUE dans la balise.

    La balise ouvrante n'est écrite QU'ICI, une fois l'issue connue : l'écrire avant l'exécution
    obligerait à la corriger après coup dans un flux déjà parti au client.
    """
    ouvrante = BALISE_SORTIE_OUVRANTE if succes else BALISE_SORTIE_ECHEC
    return f"{ouvrante}{texte}{BALISE_SORTIE_FERMANTE}{BALISE_OUTIL_FERMANTE}\n\n"


async def _jouer_appels(
    appels: list[dict[str, Any]],
    messages: list[MessageChat],
    contexte: ContexteExecution,
    etat: EtatBoucle,
    texte: str,
) -> AsyncIterator[dict[str, Any]]:
    """Exécute les appels d'un tour et met l'état de conduite à jour."""
    etat.tours_muets = 0
    etat.textes.append(texte)
    avant = etat.aboutis
    async for etape in _executer_appels(appels, messages, contexte, etat.echecs_vus):
        if isinstance(etape.get("texte"), str):
            yield {"texte": etape["texte"]}
        etat.aboutis += 1 if etape.get("succes") else 0
    if etat.aboutis > avant:
        # Un outil a abouti : l'ardoise des relances est effacée, comme celle des redites.
        # MESURÉ le 2026-08-16 : relancé une fois, le modèle écrit bien son fichier — puis referme
        # aussitôt sur « Le voici : » sans appeler `presenter_fichier`. Un compteur global le
        # laissait passer. Ce qu'il faut borner, c'est la promesse SANS PROGRÈS ; une promesse qui
        # suit un travail réel mérite le même traitement que la première.
        etat.relances = 0
        etat.relances_promesse = 0


async def _executer_appels(
    appels: list[dict[str, Any]],
    messages: list[MessageChat],
    contexte: ContexteExecution,
    echecs_vus: set[str],
) -> AsyncIterator[dict[str, Any]]:
    """Exécute les appels demandés, en annonçant chacun dans le flux, et enrichit la conversation.

    `echecs_vus` porte les appels déjà échoués sans qu'aucun autre n'ait abouti depuis ; voir
    `_REDITE`. Rend `succes` au fil de l'eau, pour que l'appelant sache si quoi que ce soit a abouti.
    """
    from backend.outils import executer

    for appel in appels:
        nom, arguments = _texte_appel(appel)
        # L'entrée part AVANT l'exécution : c'est ce qui rend l'attente lisible plutôt que muette.
        entree = f"{BALISE_ENTREE_OUVRANTE}{_annonce(nom, arguments)}{BALISE_ENTREE_FERMANTE}"
        yield {"texte": f"{BALISE_OUTIL_OUVRANTE}{entree}"}
        signature = _signature(nom, arguments)
        if signature in echecs_vus:
            logger.warning("Appel {} déjà échoué à l'identique : non réexécuté.", nom)
            texte, succes = _REDITE, False
        else:
            resultat = await executer(nom, arguments, contexte)
            texte, succes = resultat.texte, resultat.succes
            if succes:
                echecs_vus.clear()
            else:
                echecs_vus.add(signature)
        yield {"texte": _bloc_sortie(texte, succes), "succes": succes}
        # Rôle `tool`, contenu NU. Le gabarit l'enveloppe lui-même dans `<tool_response>` : c'est
        # le canal que le modèle a appris à l'entraînement, et il ne le confond pas avec sa propre
        # prose. L'ancienne forme — rôle `assistant` préfixé « [outil nom — résultat] » — était un
        # format inventé par nous, et le modèle a fini par l'imiter au lieu d'appeler l'outil.
        messages.append(MessageChat(role="tool", content=texte))


class MoteurChat:
    """Adaptateur du superviseur vers le port de génération de `chat`.

    Rend des dictionnaires — `{"texte": …}` puis `{"tokens_generes": …, "tokens_par_seconde": …}` —
    que `chat.adaptation_inference` normalise. Ce détour évite d'importer les modèles de `chat`
    ici, donc un cycle entre les deux domaines.
    """

    def generer(self, requete: object) -> AsyncIterator[dict[str, Any]]:
        """Ouvre le flux. Rend l'itérateur SANS être une coroutine, comme l'exige le port."""
        return self._flux(requete)

    async def mesurer_occupation(self, messages: object) -> Any:
        """Occupation de la fenêtre pour CES messages ET les définitions d'outils envoyées avec.

        Rend l'`OccupationContexte` du domaine inference ; `chat.adaptation_inference` le normalise.
        Les définitions d'outils sont comptées : la génération les envoie à CHAQUE tour
        (`charge["tools"]`), et sur le harnais réel elles pèsent plus de mille tokens — les ignorer
        laissait le prompt réel franchir la fenêtre AVANT que la compaction ne se déclenche. Seuls
        restent hors décompte les marqueurs de rôle du gabarit et le BOS, de l'ordre de la dizaine
        de tokens par message, largement couverts par la marge de 10 % du seuil.
        """
        return await superviseur.compter_contexte(_socle_outils_json(), _messages_depuis(messages))

    async def resumer(
        self, a_resumer: str, resume_precedent: str, langue: str, max_tokens: int
    ) -> str | None:
        """Résumé cumulatif orienté agent, produit par le modèle chargé — ou `None` s'il échoue."""
        from backend.inference.resume_compaction import produire_resume

        return await produire_resume(a_resumer, resume_precedent, langue, max_tokens)

    async def _flux(self, requete: object) -> AsyncIterator[dict[str, Any]]:
        """Assemble le tour complet : contexte d'exécution, boucle d'outils, mesure du débit."""
        from backend.outils import format_moteur

        messages = _messages_depuis(getattr(requete, "messages", None))
        options = _options_depuis(getattr(requete, "parametres", None))
        contexte = _contexte_execution(requete)
        debut = time.monotonic()
        tokens = 0

        async for etape in self._boucle_outils(
            messages, options, format_moteur(_outils_demandes(requete)), contexte
        ):
            tokens += int(etape.pop("tokens", 0) or 0)
            if "texte" in etape:
                yield {"texte": etape["texte"]}

        ecoule = time.monotonic() - debut
        # Le compte de tokens est celui des morceaux réellement reçus, et le débit en découle. Si
        # aucun token n'est passé, on rend `None` plutôt qu'un zéro qui ressemblerait à une mesure.
        yield {
            "tokens_generes": tokens or None,
            "tokens_par_seconde": (tokens / ecoule) if tokens and ecoule > 0 else None,
        }

    async def _diffuser(
        self,
        messages: list[MessageChat],
        options: OptionsGeneration,
        outils: list[dict[str, Any]] | None,
        recu: list[str],
        raisons: list[str | None],
    ) -> AsyncIterator[dict[str, Any]]:
        """Un tour de moteur, diffusé token par token, en accumulant le texte reçu dans `recu`.

        `recu` sert deux fois : il porte le texte où chercher les appels d'outils, et sa longueur
        EST le compte de tokens du tour — un seul endroit qui compte, donc pas de divergence
        possible entre ce qui est affiché et ce qui est mesuré.

        `raisons` recueille la raison d'arrêt du moteur. Elle existait déjà sur le morceau de fin et
        n'était lue par personne : c'est elle qui dit si la réponse est complète ou tronquée.
        """
        async for morceau in superviseur.generer(messages, options, outils):
            if morceau.type == "token" and morceau.contenu:
                recu.append(morceau.contenu)
                yield {"texte": morceau.contenu}
            elif morceau.type == "erreur":
                # Le flux HTTP est déjà ouvert : signaler dedans est la seule façon d'informer.
                logger.error("Génération interrompue par le moteur : {}", morceau.contenu)
                raise RuntimeError(morceau.contenu or "Le moteur a interrompu la génération.")
            elif morceau.type == "fin":
                raisons.append(morceau.raison_arret)

    async def _diffuser_complet(
        self,
        messages: list[MessageChat],
        options: OptionsGeneration,
        outils: list[dict[str, Any]] | None,
        recu: list[str],
    ) -> AsyncIterator[dict[str, Any]]:
        """Diffuse un tour et le REPREND tant que le moteur l'a coupé faute de place.

        Le seul objectif : une réponse ne s'arrête jamais avant d'être complète. La reprise passe
        par un tour d'assistant portant ce qui a déjà été écrit, suivi d'une consigne de reprise —
        forme qui marche avec tous les gabarits présents, là où un pré-remplissage de tour dépendrait
        de l'un d'eux. `recu` continue de s'accumuler, donc les appels d'outils sont cherchés dans le
        texte ENTIER, appel coupé en deux compris.

        Les outils restent déclarés pendant la reprise : la coupure survient justement souvent au
        milieu d'un appel, et c'est le cas qu'il faut pouvoir réparer.
        """
        raisons: list[str | None] = []
        async for morceau in self._diffuser(messages, options, outils, recu, raisons):
            yield morceau
        # `length` recouvre DEUX causes que le moteur ne distingue pas : la fenêtre est pleine, ou
        # le plafond demandé est atteint. Reprendre dans le second cas reviendrait à passer outre un
        # réglage que l'utilisateur a posé exprès. `max_tokens` absent veut dire « aucun plafond » :
        # c'est le seul cas où une coupure est subie et non voulue.
        if options.max_tokens is not None:
            if raisons and raisons[-1] == "length":
                logger.info("Réponse arrêtée au plafond demandé ({} tokens) : pas de reprise.", options.max_tokens)
            return
        for essai in range(CONTINUATIONS_MAX):
            if not raisons or raisons[-1] != "length":
                return
            suite = _prompt_de_reprise(messages, recu)
            libres = await self._tokens_libres(suite)
            if libres is not None and libres < MARGE_CONTINUATION_TOKENS:
                logger.warning("Reprise impossible : {} tokens libres dans la fenêtre.", libres)
                yield {"texte": AVERTISSEMENT_FENETRE_PLEINE}
                return
            logger.info("Réponse coupée par la fenêtre : reprise {}/{}.", essai + 1, CONTINUATIONS_MAX)
            raisons.clear()
            async for morceau in self._diffuser(suite, options, outils, recu, raisons):
                yield morceau
        logger.warning("Borne de {} reprises atteinte : la réponse reste incomplète.", CONTINUATIONS_MAX)
        yield {"texte": AVERTISSEMENT_FENETRE_PLEINE}

    async def _tokens_libres(self, messages: list[MessageChat]) -> int | None:
        """Place restante dans la fenêtre, ou `None` si elle n'est pas mesurable.

        `None` n'autorise pas à supposer qu'il reste de la place : il laisse simplement la reprise
        se tenter, bornée par `CONTINUATIONS_MAX`. Un comptage indisponible — moteur occupé, pas de
        tokenizer — ne doit pas décider à la place du moteur qu'une réponse est finie.
        """
        try:
            occupation = await superviseur.compter_contexte("", messages)
        except Exception as exc:  # noqa: BLE001 — une mesure absente ne doit jamais couper la réponse
            logger.warning("Place restante non mesurable ({}) : reprise tentée quand même.", exc)
            return None
        return occupation.tokens_libres if occupation.mesurable else None

    async def _boucle_outils(
        self,
        messages: list[MessageChat],
        options: OptionsGeneration,
        outils: list[dict[str, Any]],
        contexte: ContexteExecution,
    ) -> AsyncIterator[dict[str, Any]]:
        """Les tours d'outils, puis la clôture si la borne est atteinte. Rend aussi `tokens` par tour.

        Un seul appel au moteur par tour, outils déclarés dedans ; le tour suivant n'a lieu que si
        le modèle a réellement demandé un outil. Les outils restent déclarés à CHAQUE tour — voir
        `TOURS_OUTILS_MAX` pour la mesure qui a fait abandonner l'inverse.

        La CONDUITE — combien de tours, quand relancer, quand constater un radotage — vient de
        `harnais.py` et non de constantes locales : c'est ce qui permet de la faire varier sans
        toucher au transport, et de comparer deux conduites à outils et modèle constants.
        """
        etat = EtatBoucle(harnais=harnais.choisir(harnais.harnais_demande(options)),
                          outils_declares=outils or None)
        while not budget_epuise(etat):
            messages = _avec_avertissement(messages, etat)
            recu: list[str] = []
            async for morceau in self._diffuser_complet(messages, options, etat.outils_declares, recu):
                yield morceau
            yield {"tokens": len(recu)}
            texte = "".join(recu)
            # Sans registre, un `<tool_call>` écrit par le modèle est une hallucination : l'exécuter
            # produirait un bloc « outil inconnu » là où il n'y a simplement aucun outil.
            appels = _appels_demandes(texte) if outils else []
            if not appels:
                consigne = consigne_de_relance(texte, etat, bool(outils))
                if consigne is None:
                    if not etat.promesse_en_suspens:
                        return
                    # Sortir de la boucle plutôt que rendre la main : la clôture ci-dessous doit
                    # produire une VRAIE réponse là où le modèle n'a laissé qu'une intention.
                    yield {"texte": BALISE_FIN_ETAPE}
                    messages = relancer(messages, texte, CONSIGNE_CLOTURE_PROMESSE)
                    break
                yield {"texte": BALISE_FIN_ETAPE}
                messages = relancer(messages, texte, consigne)
                continue
            # Ce tour appelait un outil : ce qui vient d'être écrit était du commentaire de travail,
            # pas la réponse. On le signale au lieu de le laisser passer pour telle. Le balisage de
            # l'appel, lui, ne repart PAS au moteur — sinon il lui sert de modèle à recopier.
            yield {"texte": BALISE_FIN_ETAPE}
            harnais.rearmer_relances(etat)
            messages = list(messages) + [
                MessageChat(role="assistant", content=_sans_appels_outils(texte))
            ]
            async for etape in _jouer_appels(appels, messages, contexte, etat, texte):
                yield etape
            _prolonger_si_demande(etat)
        async for morceau in self._cloturer(messages, options, etat.aboutis, etat.harnais):
            yield morceau

    async def _cloturer(
        self, messages: list[MessageChat], options: OptionsGeneration, aboutis: int,
        conduite: harnais.Harnais = harnais.DEFAUT,
    ) -> AsyncIterator[dict[str, Any]]:
        """Tour final sans outil, quand les trois tours ont tous demandé un outil.

        Aucun d'eux n'a donc produit de réponse : sortir ici laissait la conversation sans un mot,
        et l'interface affichait « le modèle n'a rien écrit en dehors de son raisonnement » sous une
        pile de blocs d'outils. Ce n'est pas une quatrième chance donnée à l'outil, c'est la clôture.

        Quand RIEN n'a abouti, le modèle est prévenu explicitement. Sans ce rappel, il terminait sur
        « Voici le nouveau fichier, ouvrez la carte ci-dessus » alors qu'aucun fichier n'existait et
        qu'aucune carte n'était affichée (mesuré le 2026-08-16). Laisser annoncer un résultat
        inexistant est pire qu'échouer : l'utilisateur ne peut même pas savoir que ça a raté.
        """
        logger.warning("Borne de {} tours d'outils atteinte ({}) : tour de clôture sans outil.",
                       conduite.tours_outils_max, conduite.nom)
        if aboutis == 0:
            logger.warning("Aucun outil abouti sur ce tour : clôture avec consigne explicite.")
            messages = list(messages) + [MessageChat(role="tool", content=_AUCUN_OUTIL_ABOUTI)]
        yield {"texte": BALISE_FIN_ETAPE}
        recu: list[str] = []
        async for morceau in self._diffuser_complet(messages, options, None, recu):
            yield morceau
        yield {"tokens": len(recu)}


def _socle_outils_json() -> str:
    """Définitions d'outils sérialisées comme la génération les envoie, pour les compter.

    La génération envoie TOUS les outils du registre à chaque tour (le port ne transporte pas de
    sélection). On mesure donc le même socle. Un registre indisponible rend une chaîne vide : une
    mesure sans les outils vaut mieux qu'une absence de mesure, et la marge du seuil l'absorbe.
    """
    import json

    try:
        from backend.outils import format_moteur

        outils = format_moteur(None)
    except Exception as exc:  # noqa: BLE001 — l'absence d'outils ne doit pas empêcher de mesurer
        logger.debug("Définitions d'outils non mesurables ({}) : socle d'outils compté à vide.", exc)
        return ""
    return json.dumps(outils, ensure_ascii=False)


def _outils_demandes(requete: object) -> list[str] | None:
    """Sélection d'outils portée par la requête, ou `None` pour tous.

    Lue par `getattr` : le contrat des moteurs n'a pas à connaître un réglage de conversation, et
    l'absence du champ reste le cas normal tant qu'aucun appelant ne le transmet. `[]` traverse
    intact — c'est « aucun outil », pas « pas de préférence ».
    """
    valeur = getattr(requete, "outils_actifs", None)
    if isinstance(valeur, list):
        return [str(nom) for nom in valeur]
    return None


def _contexte_execution(requete: object) -> ContexteExecution:
    """Identité de la conversation et racine de son bac, pour l'exécution des outils.

    L'identité doit atteindre l'exécution (plan d'exécution, 2.5) : sans elle, un outil confiné
    écrirait dans le bac de n'importe qui. Elle est obligatoire sur `RequeteGeneration` ; son
    absence signale un appelant qui viole le contrat du port, pas un cas à dégrader en silence.

    Le bac est le dossier de la conversation dans `atelier_workspace`, volume PARTAGÉ avec le
    conteneur atelier : ce que `ecrire_fichier` écrit ici, le shell de l'atelier le voit sous
    `/workspace/<conversation_id>`, et réciproquement. Le suffixe `<conversation_id>` est ce que
    `bac_a_sable._sous_dossier` renvoie à l'atelier — les deux dérivations doivent rester alignées.
    """
    from backend.core import get_settings
    from backend.outils.contrat import ContexteExecution

    conversation_id = getattr(requete, "conversation_id", None)
    if not conversation_id:
        raise ValueError("RequeteGeneration sans conversation_id : contrat du port violé.")
    projet = getattr(requete, "projet", None)
    if projet:
        from backend.projets import chemin_projet

        return ContexteExecution(conversation_id=conversation_id, racine_bac=chemin_projet(projet), projet=projet)
    return ContexteExecution(
        conversation_id=conversation_id,
        racine_bac=get_settings().atelier_workspace / conversation_id,
    )


def creer_moteur_chat() -> MoteurChat:
    """Fabrique cherchée par `chat.adaptation_inference` au premier besoin de génération."""
    return MoteurChat()


__all__ = [
    # Planification — pure, testable sans GPU
    "DemandeDeChargement",
    "MetadonneesModele",
    "PlanDeChargement",
    "PreferencesUtilisateur",
    "ProfilMachine",
    "planifier",
    "degrader",
    # Exécution
    "superviseur",
    "MessageChat",
    "OptionsGeneration",
    # Pont vers le domaine chat
    "MoteurChat",
    "creer_moteur_chat",
]
