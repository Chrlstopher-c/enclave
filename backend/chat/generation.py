"""Orchestration d'un tour de génération : contexte, streaming, annulation, persistance.

Le tour est coupé en deux temps volontairement distincts :

- `preparer()` est synchrone et échoue tôt — conversation inconnue, génération déjà en cours. Tant
  que le flux n'a pas commencé, une erreur peut encore devenir un vrai statut HTTP.
- `diffuser()` est l'itérateur asynchrone. Une fois les en-têtes partis, plus aucun statut n'est
  négociable : tout échec y devient un événement `erreur` dans le flux.

Ce que ce module ne fait pas, et ne fera pas : estimer un nombre de tokens. Si le moteur ne
rapporte pas ses compteurs, ils restent nuls en base. La v1 les fabriquait (`len // 4`), ce qui
donnait des statistiques crédibles et fausses.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from loguru import logger

from backend.chat import annulation, compaction, depot, port_inference
from backend.chat.annulation import GenerationActive
from backend.chat.compaction import MessageAncre
from backend.chat.erreurs import BrancheInvalide
from backend.chat.modeles import (
    MAX_TOKENS_PLAFOND,
    DemandeEdition,
    DemandeGeneration,
    DemandeRejeu,
    EvenementCompaction,
    EvenementDebut,
    EvenementErreur,
    EvenementFin,
    EvenementFlux,
    EvenementFragment,
    InfoCompaction,
    MessageChat,
    ParametresEchantillonnage,
    ReglagesConversation,
)
from backend.chat.port_inference import (
    FragmentTexte,
    MessageInference,
    PieceJointe,
    RequeteGeneration,
    StatistiquesGeneration,
)
from backend.core import EchoHubError, MoteurIndisponible, get_settings


def _delai_inactivite_s() -> float:
    """Délai au-delà duquel un moteur muet est tenu pour mort — configurable, jamais figé.

    Lu à chaque attente plutôt que gelé à l'import : `ECHOHUB_DELAI_INACTIVITE_S` doit pouvoir être
    relevé sans reconstruire le module. Le préremplissage d'un long prompt sur le 35B (experts
    déportés en RAM) peut dépasser plusieurs MINUTES avant le premier token, sans réarmer le
    compteur — 180 s coupait alors une génération qui réfléchissait. Le défaut (900 s) laisse ce
    travail aboutir, tout en finissant par voir un vrai deadlock.
    """
    return get_settings().delai_inactivite_generation_s

# Certains moteurs émettent un fragment par morceau de token (caractère UTF-8 multi-octets, espace
# de tête). Cette marge borne la boucle de diffusion sans couper une génération légitime.
MARGE_FRAGMENTS_PAR_TOKEN = 4


@dataclass(slots=True)
class PreparationGeneration:
    """Tout ce que `diffuser()` doit savoir, figé avant l'ouverture du flux.

    `parent_id` est décidé ICI, une fois, et transporté jusqu'à la persistance : relire la feuille
    active au moment d'écrire la réponse rattacherait le message à ce que la conversation est
    devenue entre-temps, pas à ce sur quoi la génération a réellement travaillé.
    """

    conversation_id: str
    message_id: str
    modele_id: str | None
    requete: RequeteGeneration
    generation: GenerationActive
    parent_id: str | None = None
    message_utilisateur_id: str | None = None
    # Matériau de compaction, figé avec le reste : le socle d'outils (`entete`) et l'historique
    # porteur d'identités (`ancres`), pour que la décision de compaction — asynchrone, prise à
    # l'ouverture du flux — sache où couper en termes de messages réels de la base.
    entete: str = ""
    ancres: list[MessageAncre] = field(default_factory=list)
    # Balise produite ce tour, à persister APRÈS l'écriture du message assistant. `None` = aucune
    # compaction ce tour.
    compaction: InfoCompaction | None = None


@dataclass(slots=True)
class _EtatFlux:
    """État mutable d'un flux en cours, rempli au fil des fragments."""

    debut: float = field(default_factory=time.perf_counter)
    texte: str = ""
    fragments: int = 0
    tokens_generes: int | None = None
    tokens_par_seconde: float | None = None
    interrompu: bool = False

    def duree_ms(self) -> int:
        return max(0, round((time.perf_counter() - self.debut) * 1000))


def preparer(conversation_id: str, demande: DemandeGeneration) -> PreparationGeneration:
    """Valide, persiste le message utilisateur et réserve la conversation. Peut lever.

    Le message s'accroche à la feuille active : on prolonge la branche que l'utilisateur a sous les
    yeux, jamais celle qu'il a quittée.
    """
    conversation = depot.exiger_conversation(conversation_id)
    reglages = depot.lire_reglages(conversation_id)
    modele_id = demande.modele_id or _modele_charge() or conversation.modele_id
    message_assistant = _identifiant_provisoire()
    generation = annulation.reserver(conversation_id, message_assistant)
    try:
        message_utilisateur = depot.ajouter_message(
            conversation_id,
            role="user",
            contenu=demande.contenu,
            parent_id=depot.feuille_active(conversation_id),
        )
        _lier_fichiers(conversation_id, demande.fichier_ids, message_utilisateur.id)
        if modele_id is not None and modele_id != conversation.modele_id:
            depot.definir_modele_conversation(conversation_id, modele_id)
        contexte = _construire_contexte(conversation_id, reglages, message_utilisateur.id)
    except EchoHubError:
        annulation.liberer(generation)
        raise

    return _preparation(
        conversation_id=conversation_id,
        message_assistant=message_assistant,
        modele_id=modele_id,
        parametres=demande.parametres or reglages.parametres,
        contexte=contexte,
        generation=generation,
        ancre=message_utilisateur.id,
        message_utilisateur_id=message_utilisateur.id,
    )


def preparer_rejeu(conversation_id: str, message_id: str, demande: DemandeRejeu) -> PreparationGeneration:
    """Rejoue un message dans une nouvelle sous-branche : l'existante n'est ni modifiée ni perdue."""
    return _preparer_branche(conversation_id, message_id, demande, contenu=None)


def preparer_edition(conversation_id: str, message_id: str, demande: DemandeEdition) -> PreparationGeneration:
    """Édite un message utilisateur : son texte corrigé devient une branche sœur, l'original reste."""
    return _preparer_branche(conversation_id, message_id, demande, contenu=demande.contenu)


def _preparer_branche(
    conversation_id: str,
    message_id: str,
    demande: DemandeRejeu,
    contenu: str | None,
) -> PreparationGeneration:
    """Ouvre une branche sœur du message visé, puis prépare la génération qui l'y prolonge."""
    conversation = depot.exiger_conversation(conversation_id)
    cible = depot.exiger_message(conversation_id, message_id)
    _verifier_branchable(cible, contenu)
    reglages = depot.lire_reglages(conversation_id)
    modele_id = demande.modele_id or _modele_charge() or conversation.modele_id
    message_assistant = _identifiant_provisoire()
    generation = annulation.reserver(conversation_id, message_assistant)
    try:
        ancre, message_utilisateur_id = _ancrer_branche(cible, contenu)
        contexte = _construire_contexte(conversation_id, reglages, ancre)
        # Écrit APRÈS la construction du contexte : une branche refusée ne doit pas déplacer la
        # vue vers un point de l'arbre où rien ne sera généré. Tant que la nouvelle réponse n'est
        # pas persistée, la vue résolue redescend sur la variante existante (cf. `resoudre_feuille`).
        depot.definir_feuille_active(conversation_id, ancre)
    except EchoHubError:
        annulation.liberer(generation)
        raise
    return _preparation(
        conversation_id=conversation_id,
        message_assistant=message_assistant,
        modele_id=modele_id,
        parametres=demande.parametres or reglages.parametres,
        contexte=contexte,
        generation=generation,
        ancre=ancre,
        message_utilisateur_id=message_utilisateur_id,
    )


def _verifier_branchable(cible: MessageChat, contenu: str | None) -> None:
    """Refuse les branchements qui n'ont pas de sens, avec la raison exacte.

    Réécrire une réponse du modèle en ferait un faux enregistrement de ce qu'il a produit : seule
    la parole de l'utilisateur s'édite. Un message `system` n'est pas un tour de conversation mais
    un réglage — il ne se rejoue pas.
    """
    if cible.role not in ("user", "assistant"):
        raise BrancheInvalide(f"Un message de rôle « {cible.role} » ne porte pas de branche.")
    if contenu is not None and cible.role != "user":
        raise BrancheInvalide("Seul un message utilisateur peut être édité.")


def _ancrer_branche(cible: MessageChat, contenu: str | None) -> tuple[str | None, str | None]:
    """Point d'accroche de la réponse à venir, et message utilisateur créé s'il y en a un.

    Une réponse se rejoue depuis SON parent : la nouvelle réponse devient sa sœur, sans qu'aucun
    message ne soit récrit. Un message utilisateur (rejeu à l'identique ou édition) est recopié en
    sœur : la branche s'ouvre à partir du même parent, et l'original garde sa propre suite.
    """
    if cible.role == "assistant":
        return cible.parent_id, None
    nouveau = depot.ajouter_message(
        cible.conversation_id,
        role="user",
        contenu=cible.contenu if contenu is None else contenu,
        parent_id=cible.parent_id,
    )
    return nouveau.id, nouveau.id


def _lier_fichiers(conversation_id: str, fichier_ids: list[str], message_id: str) -> None:
    """Rattache au message qui vient d'être écrit les pièces jointes déjà déposées dans le magasin.

    Import local : `backend.fichiers` dépend de `backend.chat` (il vérifie qu'une conversation
    existe avant tout dépôt) — l'importer en tête de module créerait un cycle, comme le documente
    déjà `backend.chat.depot._supprimer_dossier_fichiers`.
    """
    if not fichier_ids:
        return
    from backend.fichiers import lier_fichiers_au_message

    lier_fichiers_au_message(conversation_id, fichier_ids, message_id)


def _modele_charge() -> str | None:
    """Modèle RÉELLEMENT chargé dans le moteur à cet instant, ou `None` si rien n'est prêt.

    C'est lui qui doit être attribué à la réponse, pas celui mémorisé sur la conversation : ce
    dernier est fixé à la création et ne bouge plus. Changer de modèle en cours de conversation
    faisait donc attribuer les nouvelles réponses à l'ancien modèle — l'attribution mentait sur ce
    qui avait réellement produit les tokens, alors qu'elle sert justement à qualifier les mesures
    affichées à côté (débit, nombre de tokens).

    Import local et échec silencieux : `chat` reste utilisable sans le domaine `inference`, comme
    partout ailleurs dans ce fichier.
    """
    try:
        from backend.inference import superviseur

        statut = superviseur.statut()
        return statut.modele if statut.etat.value == "pret" else None
    except Exception as exc:  # noqa: BLE001 — l'attribution est un confort, jamais une condition
        logger.debug("Modèle chargé indéterminable ({}) : repli sur celui de la conversation.", exc)
        return None


@dataclass(slots=True)
class _ContexteConstruit:
    """Ce que l'assemblage du contexte produit : le flat envoyé au moteur, et de quoi le compacter."""

    entete: str
    ancres: list[MessageAncre]
    messages: list[MessageInference]
    outils_actifs: list[str] | None = None
    projet: str | None = None


def _preparation(
    *,
    conversation_id: str,
    message_assistant: str,
    modele_id: str | None,
    parametres: ParametresEchantillonnage,
    contexte: _ContexteConstruit,
    generation: GenerationActive,
    ancre: str | None,
    message_utilisateur_id: str | None,
) -> PreparationGeneration:
    """Assemble la préparation. Un seul endroit construit la requête envoyée au moteur."""
    requete = RequeteGeneration(
        messages=contexte.messages, parametres=parametres, modele_id=modele_id,
        conversation_id=conversation_id, outils_actifs=contexte.outils_actifs, projet=contexte.projet,
    )
    return PreparationGeneration(
        conversation_id=conversation_id,
        message_id=message_assistant,
        modele_id=modele_id,
        requete=requete,
        generation=generation,
        parent_id=ancre,
        message_utilisateur_id=message_utilisateur_id,
        entete=contexte.entete,
        ancres=contexte.ancres,
    )


def _identifiant_provisoire() -> str:
    """Identifiant annoncé au client dès l'ouverture du flux, avant que le message n'existe en base."""
    return str(uuid.uuid4())


def _construire_contexte(
    conversation_id: str,
    reglages: ReglagesConversation,
    ancre: str | None,
) -> _ContexteConstruit:
    """Assemble prompt système + chemin jusqu'à l'ancre, en messages, jamais en tokens estimés.

    L'historique est le CHEMIN de la branche visée, pas tous les messages de la conversation : une
    variante abandonnée ne doit plus peser sur ce que le modèle lit.

    Rend aussi le socle (`entete`) et les `ancres` — chaque message d'historique avec son identité
    réelle en base —, matériau que la compaction consomme pour couper à un point qui survit au
    rechargement. La requête moteur, elle, reste le socle suivi des messages, exactement comme avant.
    """
    historique = _historique_branche(conversation_id, reglages, ancre)
    entete = _socle_outils(reglages)
    # Un message vide fait échouer la tokenisation de plusieurs gabarits de chat ; un message
    # `system` en historique doublonnerait le prompt système, qui est un réglage et non un tour.
    pieces_par_message = _pieces_du_contexte(historique)
    ancres = [
        MessageAncre(
            id=message.id,
            message=MessageInference(
                role=message.role,
                contenu=message.contenu,
                pieces=pieces_par_message.get(message.id, []),
            ),
        )
        for message in historique
        if message.role != "system" and message.contenu.strip()
    ]
    messages: list[MessageInference] = []
    if entete.strip():
        messages.append(MessageInference(role="system", contenu=entete))
    messages.extend(ancre.message for ancre in ancres)
    if not messages:
        # Le port exige au moins un message : une erreur métier lisible vaut mieux qu'une
        # ValidationError remontée en 500 depuis la couche HTTP.
        raise BrancheInvalide("Aucun contenu exploitable en amont de ce point.")
    return _ContexteConstruit(entete=entete, ancres=ancres, messages=messages,
                              outils_actifs=reglages.outils_actifs, projet=reglages.projet)


def contexte_de_branche(conversation_id: str, feuille: str | None) -> _ContexteConstruit:
    """Contexte tel qu'il partirait au moteur pour la branche qui finit à `feuille` (compaction manuelle)."""
    return _construire_contexte(conversation_id, depot.lire_reglages(conversation_id), feuille)


def _socle_outils(reglages: ReglagesConversation) -> str:
    """Socle du harnais + prompt de conversation, ou le seul prompt si le harnais est indisponible.

    Le socle énonce les outils réellement disponibles. Sans lui, les modèles chargés ici annoncent
    savoir chercher sur le web puis fabriquent des résultats — constaté le 2026-08-14. Import local :
    `chat` reste chargeable sans `outils`, comme sans `inference` ; un harnais absent dégrade le
    prompt, il n'empêche pas la conversation.
    """
    try:
        from backend.outils import prompt_systeme

        return prompt_systeme(reglages.prompt_systeme, _modele_charge() or "", reglages.outils_actifs,
                              reglages.projet)
    except Exception as exc:  # noqa: BLE001 — le socle est un plus, jamais une condition
        logger.warning("Socle d'outils indisponible ({}) : prompt de conversation seul.", exc)
        return reglages.prompt_systeme


def _historique_branche(
    conversation_id: str,
    reglages: ReglagesConversation,
    ancre: str | None,
) -> list[MessageChat]:
    """Chemin racine → ancre, tronqué en NOMBRE DE MESSAGES quand l'utilisateur l'a demandé."""
    historique = [] if ancre is None else depot.chemin_jusqua(conversation_id, ancre)
    if not historique:
        raise BrancheInvalide(
            "Aucun historique en amont de ce point : il n'y a rien à envoyer au moteur.",
            details={"conversation_id": conversation_id, "ancre": ancre},
        )
    if reglages.historique_max_messages is None:
        return historique
    return historique[-reglages.historique_max_messages :]


def _pieces_du_contexte(historique: list[MessageChat]) -> dict[str, list[PieceJointe]]:
    """Pièces jointes de chaque message de l'historique, converties à la forme attendue par le port.

    Une seule requête groupée (`pieces_pour_messages`), jamais une par message : l'historique peut
    compter des dizaines de messages, et le contexte se reconstruit à chaque tour de génération.
    Import local pour la même raison de cycle que `_lier_fichiers`.
    """
    from backend.fichiers import chemin_disque, pieces_pour_messages

    brutes = pieces_pour_messages([message.id for message in historique])
    return {
        message_id: [
            PieceJointe(chemin=chemin_disque(fichier), type_mime=fichier.type_mime, nom_affiche=fichier.nom_affiche)
            for fichier in fichiers
        ]
        for message_id, fichiers in brutes.items()
    }


# Tâches de génération vivantes, gardées en référence forte le temps qu'elles s'achèvent.
#
# `asyncio.create_task` ne suffit pas seul : la boucle ne détient qu'une référence FAIBLE vers la
# tâche, qui peut donc être ramassée en pleine exécution. C'est le piège documenté dans la doc
# d'asyncio, et il se manifesterait ici précisément quand plus personne ne lit le flux — le cas
# qu'on cherche justement à faire survivre.
_taches_en_cours: set[asyncio.Task[None]] = set()


async def _produire(
    preparation: PreparationGeneration, etat: _EtatFlux, file: asyncio.Queue[EvenementFlux | None]
) -> None:
    """Mène la génération jusqu'à son terme et la persiste, que quelqu'un l'écoute ou non.

    C'est la moitié qui NE DOIT PAS dépendre du client. Elle vivait auparavant dans le générateur
    du flux : quand le navigateur fermait la connexion — un téléphone qui passe en veille suffit —
    Starlette détruisait ce générateur, `GeneratorExit` remontait, et la génération s'arrêtait net.
    L'utilisateur retrouvait son message envoyé et une réponse vide, sans savoir si quelque chose
    tournait encore. Mesuré sur mobile le 2026-08-16, deux fois de suite.

    Les événements partent dans une file plutôt que d'être rendus directement : le lecteur peut
    disparaître sans que la production s'arrête. `None` clôt la file et n'est jamais diffusé.
    """
    erreur: EvenementErreur | None = None
    try:
        await _instantane_projet(preparation)
        await _compacter_si_besoin(preparation, file)
        async for texte in _fragments(preparation, etat):
            await file.put(EvenementFragment(texte=texte))
    except EchoHubError as exc:
        logger.error("Génération interrompue sur {} : {}", preparation.conversation_id, exc)
        erreur = EvenementErreur(code=exc.code, message=exc.message, remediation=exc.remediation)
    except Exception as exc:  # dernier filet : un moteur tiers peut lever n'importe quoi
        logger.exception("Échec inattendu de la génération sur {}", preparation.conversation_id)
        erreur = EvenementErreur(code="erreur_interne", message=str(exc))
    finally:
        annulation.liberer(preparation.generation)
        # La persistance a lieu ICI, dans la tâche, et non dans le flux : c'est ce qui garantit
        # qu'une réponse produite sans auditeur est tout de même écrite. La balise de compaction
        # suit le message assistant qu'elle précède : elle référence son identité en base, donc elle
        # ne s'écrit qu'APRÈS lui.
        erreur = _persister(preparation, etat) or erreur
        _persister_compaction(preparation, etat)
        preparation.generation.terminee.set()
        if erreur is not None:
            await file.put(erreur)
        await file.put(_evenement_fin(preparation, etat))
        await file.put(None)


async def _instantane_projet(preparation: PreparationGeneration) -> None:
    """Instantané du projet AVANT que le modèle n'y touche : c'est ce qui rend son tour annulable."""
    projet = preparation.requete.projet
    if projet is None:
        return
    from backend.projets import instantane_avant_tour

    await asyncio.to_thread(instantane_avant_tour, projet, f"avant le tour {preparation.message_id}")


async def _compacter_si_besoin(
    preparation: PreparationGeneration, file: asyncio.Queue[EvenementFlux | None]
) -> None:
    """Compacte le contexte AVANT la génération si la fenêtre approche de la saturation.

    Étape non destructive : elle ne touche ni la base ni ce que voit l'utilisateur, elle remplace
    seulement, dans `requete.messages`, les tours anciens par un résumé. En cas d'impossibilité
    (mesure absente, moteur occupé, résumé en échec), la requête part inchangée — jamais tronquée en
    silence. La balise éventuelle est émise en direct et retenue pour être persistée après le message.
    """
    try:
        moteur = port_inference.obtenir_moteur()
        chemin_ids = {ancre.id for ancre in preparation.ancres}
        active = depot.lire_compaction_active(preparation.conversation_id, chemin_ids)
        resultat = await compaction.preparer_compaction(
            moteur,
            preparation.entete,
            preparation.ancres,
            active,
            conversation_id=preparation.conversation_id,
            message_id=preparation.message_id,
        )
    except Exception as exc:  # noqa: BLE001 — la compaction est un plus, jamais une condition de génération
        logger.warning("Compaction non tentée sur {} ({}) : contexte inchangé.",
                       preparation.conversation_id, exc)
        return
    preparation.requete = preparation.requete.model_copy(update={"messages": resultat.messages})
    if resultat.info is not None:
        preparation.compaction = resultat.info
        await file.put(EvenementCompaction(compaction=resultat.info))


def _persister_compaction(preparation: PreparationGeneration, etat: _EtatFlux) -> None:
    """Écrit la balise de compaction, une fois son message assistant en base.

    Sans texte, le message assistant n'a pas été écrit (`_persister`) et la clé étrangère refuserait
    la balise : on la garde alors non persistée plutôt que de lever. Le direct l'a déjà montrée ; le
    cas — compaction déclenchée puis génération muette — est rare et sans conséquence.
    """
    if preparation.compaction is None or not etat.texte:
        return
    try:
        depot.enregistrer_compaction(preparation.compaction)
    except EchoHubError as exc:
        logger.error("Balise de compaction non persistée sur {} : {}", preparation.conversation_id, exc)


async def diffuser(preparation: PreparationGeneration) -> AsyncIterator[EvenementFlux]:
    """Diffuse au client ce que la tâche de génération produit — sans jamais la commander.

    Le départ du client ferme ce générateur ; il ne touche pas à la tâche, qui poursuit et persiste.
    C'est le sens de la séparation : la connexion HTTP transporte la réponse, elle ne la conditionne
    plus.
    """
    annulation.marquer_demarree(preparation.generation)
    etat = _EtatFlux()
    file: asyncio.Queue[EvenementFlux | None] = asyncio.Queue()

    tache = asyncio.create_task(_produire(preparation, etat, file))
    _taches_en_cours.add(tache)
    tache.add_done_callback(_taches_en_cours.discard)

    yield EvenementDebut(
        conversation_id=preparation.conversation_id,
        message_id=preparation.message_id,
        modele_id=preparation.modele_id,
        parent_id=preparation.parent_id,
        message_utilisateur_id=preparation.message_utilisateur_id,
    )
    try:
        while True:
            evenement = await file.get()
            if evenement is None:
                return
            yield evenement
    except GeneratorExit:
        # Le client est parti. On le NOTE et on ne fait rien d'autre : annuler la tâche ici
        # reproduirait exactement le défaut corrigé.
        logger.info(
            "Client déconnecté sur {} : la génération se poursuit et sera persistée.",
            preparation.conversation_id,
        )
        raise


def _evenement_fin(preparation: PreparationGeneration, etat: _EtatFlux) -> EvenementFin:
    """Dernier événement : ce qui a été mesuré, jamais ce qui aurait pu être estimé."""
    return EvenementFin(
        message_id=preparation.message_id,
        tokens_generes=etat.tokens_generes,
        tokens_par_seconde=etat.tokens_par_seconde,
        duree_ms=etat.duree_ms(),
        interrompu=etat.interrompu,
    )


async def _fragments(preparation: PreparationGeneration, etat: _EtatFlux) -> AsyncIterator[str]:
    """Boucle de lecture du moteur : bornée en itérations et en inactivité, annulable à chaque tour."""
    moteur = port_inference.obtenir_moteur()
    # `max_tokens` à `None` signifie « pas de plafond demandé » : la boucle reste bornée par le
    # plafond du domaine, qui borne aussi la valeur maximale acceptée en réglage. La borne réelle
    # de la génération est alors la fenêtre de contexte du moteur, plus le délai d'inactivité.
    plafond_tokens = preparation.requete.parametres.max_tokens or MAX_TOKENS_PLAFOND
    plafond = plafond_tokens * MARGE_FRAGMENTS_PAR_TOKEN
    iterateur = moteur.generer(preparation.requete).__aiter__()
    try:
        while etat.fragments < plafond:
            if preparation.generation.arret.is_set():
                etat.interrompu = True
                logger.info("Génération annulée sur {}", preparation.conversation_id)
                break
            element = await _element_suivant(iterateur, preparation)
            if element is _ARRET:
                etat.interrompu = True
                logger.info("Génération annulée pendant une attente sur {}", preparation.conversation_id)
                break
            if element is None:
                break
            etat.fragments += 1
            texte = _appliquer(element, etat)
            if texte:
                etat.texte += texte
                yield texte
        else:
            # `else` d'un `while` : atteint uniquement quand la condition devient fausse, donc
            # quand le plafond est saturé — les sorties par `break` (fin de flux, annulation) le
            # sautent. C'est ce qui distingue une génération coupée d'une génération terminée.
            etat.interrompu = True
            logger.warning("Plafond de {} fragments atteint sur {}", plafond, preparation.conversation_id)
    finally:
        await _fermer(iterateur)


# Rendu par `_element_suivant` quand l'arrêt est demandé PENDANT l'attente (appel d'outil en cours).
_ARRET = object()


async def _element_suivant(iterateur: AsyncIterator[object], preparation: PreparationGeneration) -> object | None:
    """Élément suivant, `None` en fin de flux, `_ARRET` si l'arrêt arrive pendant l'attente.

    L'attente fait la course avec l'arrêt : une commande d'outil peut durer 10 min sans émettre un
    token, et l'arrêt n'était vu qu'au token suivant. Une inactivité prolongée devient une erreur claire.
    """
    delai = _delai_inactivite_s()
    conversation_id = preparation.conversation_id
    suivant = asyncio.ensure_future(iterateur.__anext__())
    arret = asyncio.ensure_future(preparation.generation.arret.wait())
    try:
        faits, _ = await asyncio.wait({suivant, arret}, timeout=delai, return_when=asyncio.FIRST_COMPLETED)
    finally:
        arret.cancel()
    if suivant not in faits:
        await _abandonner(suivant, conversation_id)
        if arret in faits or preparation.generation.arret.is_set():
            return _ARRET
        logger.error("Moteur silencieux depuis {} s sur {}", delai, conversation_id)
        raise MoteurIndisponible(
            f"Le moteur n'a rien émis depuis {delai:.0f} s.",
            remediation="Vérifier l'état du moteur dans l'écran Système, puis recharger le modèle.",
        )
    try:
        return suivant.result()
    except StopAsyncIteration:
        return None


async def _abandonner(attente: asyncio.Future[object], conversation_id: str) -> None:
    """Annule l'attente du moteur (appel d'outil compris) et en absorbe la fin, journalisée."""
    attente.cancel()
    try:
        await attente
    except (asyncio.CancelledError, StopAsyncIteration):
        pass
    except Exception as exc:  # noqa: BLE001 — l'arrêt prime ; l'erreur tardive est seulement tracée
        logger.debug("Fin d'attente après arrêt sur {} : {}", conversation_id, exc)


def _appliquer(element: object, etat: _EtatFlux) -> str:
    """Range l'élément : du texte à émettre, ou des statistiques mesurées à retenir."""
    if isinstance(element, StatistiquesGeneration):
        etat.tokens_generes = element.tokens_generes
        etat.tokens_par_seconde = element.tokens_par_seconde
        return ""
    if isinstance(element, FragmentTexte):
        return element.texte
    logger.debug("Élément de flux ignoré : {}", type(element).__name__)
    return ""


async def _fermer(iterateur: AsyncIterator[object]) -> None:
    """Ferme le flux du moteur — c'est ce qui arrête réellement la génération côté moteur."""
    fermeture = getattr(iterateur, "aclose", None)
    if fermeture is None:
        return
    try:
        await fermeture()
    except Exception as exc:  # une fermeture ratée ne doit pas masquer la cause d'origine
        logger.warning("Fermeture du flux du moteur échouée : {}", exc)


def _persister(preparation: PreparationGeneration, etat: _EtatFlux) -> EvenementErreur | None:
    """Écrit la réponse produite. Un texte partiel est conservé : il a une valeur pour l'utilisateur."""
    if not etat.texte:
        return None
    try:
        depot.ajouter_message(
            preparation.conversation_id,
            role="assistant",
            contenu=etat.texte,
            identifiant=preparation.message_id,
            modele_id=preparation.modele_id,
            tokens_generes=etat.tokens_generes,
            tokens_par_seconde=etat.tokens_par_seconde,
            interrompu=etat.interrompu,
            parent_id=preparation.parent_id,
        )
    except EchoHubError as exc:
        logger.error("Réponse non persistée sur {} : {}", preparation.conversation_id, exc)
        return EvenementErreur(code=exc.code, message=exc.message, remediation=exc.remediation)
    return None
