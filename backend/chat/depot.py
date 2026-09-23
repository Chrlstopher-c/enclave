"""Persistance du domaine `chat`, bâtie sur `core.db`.

Quatre tables appartiennent au domaine et sont créées ici, de façon additive et idempotente :

- `chat_reglages` — prompt système et paramètres d'échantillonnage par conversation ;
- `chat_meta_messages` — modèle ayant produit un message, et indicateur d'interruption ;
- `chat_branche_active` — feuille affichée, c'est-à-dire quelle branche de l'arbre est la vue
  courante. L'arbre lui-même vit dans `messages.parent_id`, colonne du socle ;
- `chat_migrations` — trace des migrations de données déjà jouées, pour qu'aucune ne rejoue.

Elles n'existent pas dans le schéma de `core` et ne touchent aucune de ses tables : ce sont des
besoins propres au chat, colocalisés avec le code qui les fait vivre. Si le socle finit par les
absorber, `assurer_schema_chat()` reste sans effet (CREATE TABLE IF NOT EXISTS).

Le prompt système n'est délibérément PAS stocké comme un message de rôle `system` : c'est un
réglage qu'on modifie, pas un tour de conversation qu'on relit. Le confondre avec l'historique
obligerait à réécrire un message à chaque changement de réglage.
"""

from __future__ import annotations

import json
import sqlite3
import uuid

from loguru import logger
from pydantic import BaseModel

from backend.chat import branches
from backend.chat.erreurs import MessageIntrouvable
from backend.chat.modeles import (
    ArbreConversation,
    EtatBranche,
    InfoCompaction,
    MajConversation,
    MessageChat,
    ParametresEchantillonnage,
    ReglagesConversation,
    ResumeConversation,
    RoleMessage,
)
from backend.core import (
    ConversationIntrouvable,
    ErreurPersistance,
    execute,
    fetch_all,
    fetch_one,
    maintenant,
    transaction,
)

_SCHEMA_CHAT_SQL = """
CREATE TABLE IF NOT EXISTS chat_reglages (
    conversation_id         TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
    prompt_systeme          TEXT NOT NULL DEFAULT '',
    parametres              TEXT NOT NULL,
    historique_max_messages INTEGER,
    maj_le                  TEXT NOT NULL,
    outils_actifs           TEXT
);

CREATE TABLE IF NOT EXISTS chat_meta_messages (
    message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    modele_id  TEXT,
    interrompu INTEGER NOT NULL DEFAULT 0
);

-- Une seule ligne par conversation : la feuille affichée. `ON DELETE SET NULL` fait retomber le
-- pointeur sur la feuille naturelle dès que le message visé disparaît, sans code de rattrapage.
CREATE TABLE IF NOT EXISTS chat_branche_active (
    conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
    feuille_id      TEXT REFERENCES messages(id) ON DELETE SET NULL,
    maj_le          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_migrations (
    nom       TEXT PRIMARY KEY,
    passee_le TEXT NOT NULL
);

-- Domaine `fichiers` (lot L0 du plan d'exécution) : magasin unique des fichiers de conversation,
-- pièces jointes ET artefacts produits par le modèle, distingués par `origine`. Les octets ne
-- vivent jamais ici : `chemin_relatif` est une référence vers le disque
-- (`backend/fichiers/stockage.py`), jamais un contenu. Ajout PUREMENT additif : nouvelle table,
-- aucune ligne existante d'aucune autre table n'est touchée par sa création.
CREATE TABLE IF NOT EXISTS fichiers_conversation (
    id               TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id       TEXT REFERENCES messages(id) ON DELETE SET NULL,
    origine          TEXT NOT NULL CHECK (origine IN ('utilisateur', 'modele')),
    nom_affiche      TEXT NOT NULL,
    chemin_relatif   TEXT NOT NULL,
    type_mime        TEXT NOT NULL,
    taille_octets    INTEGER NOT NULL,
    empreinte_sha256 TEXT NOT NULL,
    cree_le          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fichiers_conversation_id ON fichiers_conversation(conversation_id);

-- Balises de compaction de contexte. AJOUT PUREMENT ADDITIF : nouvelle table, aucune ligne d'aucune
-- autre table n'est touchée. Une ligne = une compaction déclenchée avant la génération d'un message
-- assistant (`message_id`). Elle ne réduit RIEN dans `messages` : elle décrit ce que le moteur a
-- relu à la place des tours d'avant `coupe_message_id`. Le fil et l'API rendent toujours l'intégral.
CREATE TABLE IF NOT EXISTS chat_compactions (
    id                  TEXT PRIMARY KEY,
    conversation_id     TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id          TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    coupe_message_id    TEXT NOT NULL,
    nb_messages_resumes INTEGER NOT NULL,
    tokens_avant        INTEGER NOT NULL,
    tokens_apres        INTEGER NOT NULL,
    contexte_total      INTEGER NOT NULL,
    resume              TEXT NOT NULL,
    cree_le             TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_compactions_conversation ON chat_compactions(conversation_id);
"""

# Retrait de l'ancien défaut inventé de `max_tokens`. Il valait 1024 et était figé À LA CRÉATION de
# chaque conversation : toutes les conversations déjà en base le portent sans que personne ne l'ait
# choisi, et c'est ce qui coupe les réponses longues. On l'efface (la clé absente vaut `None` =
# « pas de plafond posé ici »), on ne touche à aucune autre valeur, et la trace en base garantit
# qu'un `max_tokens` remis à 1024 volontairement ne sera plus jamais effacé.
_MIGRATIONS_CHAT: tuple[tuple[str, str], ...] = (
    (
        "max_tokens_defaut_1024_vers_absent",
        "UPDATE chat_reglages SET parametres = json_remove(parametres, '$.max_tokens')"
        " WHERE json_extract(parametres, '$.max_tokens') = 1024",
    ),
)

_SELECT_MESSAGE_BASE = """
SELECT m.id, m.conversation_id, m.role, m.contenu, m.tokens_generes, m.tokens_par_seconde,
       m.cree_le, m.parent_id, meta.modele_id AS modele_id, COALESCE(meta.interrompu, 0) AS interrompu
FROM messages m
LEFT JOIN chat_meta_messages meta ON meta.message_id = m.id
"""

# `rowid` départage deux messages écrits dans la même microseconde : l'horodatage seul ne garantit
# pas un ordre stable, et un ordre instable fait varier la variante « la plus récente » d'une
# lecture à l'autre — donc la branche affichée.
_SELECT_MESSAGES = f"{_SELECT_MESSAGE_BASE} WHERE m.conversation_id = ? ORDER BY m.cree_le ASC, m.rowid ASC"

_SELECT_MESSAGE_UNIQUE = f"{_SELECT_MESSAGE_BASE} WHERE m.conversation_id = ? AND m.id = ?"

_UPSERT_FEUILLE = """
INSERT INTO chat_branche_active (conversation_id, feuille_id, maj_le) VALUES (?, ?, ?)
ON CONFLICT(conversation_id) DO UPDATE SET feuille_id = excluded.feuille_id, maj_le = excluded.maj_le
"""

_INSERT_MESSAGE = """
INSERT INTO messages (id, conversation_id, role, contenu, tokens_generes, tokens_par_seconde, cree_le, parent_id)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_META_MESSAGE = "INSERT INTO chat_meta_messages (message_id, modele_id, interrompu) VALUES (?, ?, ?)"

_SELECT_CONVERSATIONS = """
SELECT c.id, c.titre, c.modele_id, c.cree_le, c.maj_le, c.archivee,
       (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS nb_messages
FROM conversations c
"""

_COLONNES_MODIFIABLES: dict[str, str] = {"titre": "titre", "modele_id": "modele_id", "archivee": "archivee"}


class _LigneReglages(BaseModel):
    """Ligne brute de `chat_reglages` : les paramètres y sont un document JSON."""

    prompt_systeme: str
    parametres: str
    historique_max_messages: int | None = None
    # Document JSON, ou NULL pour « tous les outils » — voir `_decoder_outils`.
    outils_actifs: str | None = None


class _LigneFeuille(BaseModel):
    """Ligne brute de `chat_branche_active`."""

    feuille_id: str | None = None


def assurer_schema_chat() -> None:
    """Crée les tables du domaine si elles manquent, puis rejoue les migrations non encore passées."""
    try:
        with transaction() as conn:
            conn.executescript(_SCHEMA_CHAT_SQL)
            _appliquer_migrations_chat(conn)
    except sqlite3.Error as exc:
        logger.error("Création du schéma chat impossible : {}", exc)
        raise ErreurPersistance("Schéma du domaine chat non initialisable.", details={"cause": str(exc)}) from exc
    logger.info("Schéma du domaine chat prêt.")


def _appliquer_migrations_chat(conn: sqlite3.Connection) -> None:
    """Migrations de données du domaine : jouées une seule fois, tracées en base, journalisées."""
    passees = {str(ligne["nom"]) for ligne in conn.execute("SELECT nom FROM chat_migrations").fetchall()}
    for nom, sql in _MIGRATIONS_CHAT:
        if nom in passees:
            continue
        lignes = conn.execute(sql).rowcount
        conn.execute("INSERT INTO chat_migrations (nom, passee_le) VALUES (?, ?)", (nom, maintenant()))
        logger.info("Migration chat « {} » : {} ligne(s) touchée(s).", nom, lignes)


def creer_conversation(titre: str, modele_id: str | None, reglages: ReglagesConversation) -> ResumeConversation:
    """Insère la conversation et ses réglages dans une seule transaction."""
    identifiant = str(uuid.uuid4())
    horodatage = maintenant()
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO conversations (id, titre, modele_id, cree_le, maj_le, archivee) VALUES (?, ?, ?, ?, ?, 0)",
                (identifiant, titre, modele_id, horodatage, horodatage),
            )
            conn.execute(
                "INSERT INTO chat_reglages (conversation_id, prompt_systeme, parametres,"
                " historique_max_messages, maj_le) VALUES (?, ?, ?, ?, ?)",
                (
                    identifiant,
                    reglages.prompt_systeme,
                    reglages.parametres.model_dump_json(),
                    reglages.historique_max_messages,
                    horodatage,
                ),
            )
    except sqlite3.Error as exc:
        logger.error("Création de conversation échouée : {}", exc)
        raise ErreurPersistance("Création de la conversation impossible.", details={"cause": str(exc)}) from exc

    logger.debug("Conversation créée : {} ({})", identifiant, titre)
    return ResumeConversation(id=identifiant, titre=titre, modele_id=modele_id, cree_le=horodatage, maj_le=horodatage)


def lire_conversation(conversation_id: str) -> ResumeConversation | None:
    """Retourne la conversation, ou `None` si elle n'existe pas."""
    return fetch_one(ResumeConversation, f"{_SELECT_CONVERSATIONS} WHERE c.id = ?", (conversation_id,))


def exiger_conversation(conversation_id: str) -> ResumeConversation:
    """Comme `lire_conversation`, mais lève plutôt que de rendre `None`."""
    conversation = lire_conversation(conversation_id)
    if conversation is None:
        raise ConversationIntrouvable(f"Conversation inconnue : {conversation_id}")
    return conversation


def lister_conversations(*, archivees: bool = False) -> list[ResumeConversation]:
    """Liste les conversations actives ou archivées, la plus récemment modifiée en tête."""
    return fetch_all(
        ResumeConversation,
        f"{_SELECT_CONVERSATIONS} WHERE c.archivee = ? ORDER BY c.maj_le DESC",
        (1 if archivees else 0,),
    )


def maj_conversation(conversation_id: str, patch: MajConversation) -> ResumeConversation:
    """Applique un patch partiel. Les noms de colonnes viennent d'une liste blanche, jamais du corps."""
    exiger_conversation(conversation_id)
    modifications = patch.model_dump(exclude_unset=True, exclude_none=True)
    affectations = [f"{_COLONNES_MODIFIABLES[champ]} = ?" for champ in modifications if champ in _COLONNES_MODIFIABLES]
    if not affectations:
        return exiger_conversation(conversation_id)

    valeurs = [_valeur_sql(modifications[champ]) for champ in modifications if champ in _COLONNES_MODIFIABLES]
    affectations.append("maj_le = ?")
    valeurs.extend([maintenant(), conversation_id])
    execute(f"UPDATE conversations SET {', '.join(affectations)} WHERE id = ?", valeurs)
    return exiger_conversation(conversation_id)


def _valeur_sql(valeur: object) -> object:
    """SQLite n'a pas de booléen : les stocker en 0/1 explicitement, sans dépendre de l'adaptateur."""
    return int(valeur) if isinstance(valeur, bool) else valeur


def definir_modele_conversation(conversation_id: str, modele_id: str) -> None:
    """Mémorise le modèle réellement utilisé pour le dernier tour de cette conversation."""
    execute(
        "UPDATE conversations SET modele_id = ?, maj_le = ? WHERE id = ?",
        (modele_id, maintenant(), conversation_id),
    )


def supprimer_conversation(conversation_id: str) -> None:
    """Supprime la conversation. Messages, réglages et fichiers suivent (cascade SQL, puis disque)."""
    exiger_conversation(conversation_id)
    execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    _supprimer_dossier_fichiers(conversation_id)
    logger.debug("Conversation supprimée : {}", conversation_id)


def _supprimer_dossier_fichiers(conversation_id: str) -> None:
    """Branche la suppression du dossier disque du magasin de fichiers (lot L0).

    Import différé, pas au niveau du module : `backend.fichiers` dépend de `backend.chat`
    (vérification qu'une conversation existe avant tout dépôt) ; importer `backend.fichiers` ici
    au chargement du module créerait un cycle entre les deux domaines.

    La ligne SQL est déjà partie (cascade `ON DELETE CASCADE` sur `fichiers_conversation`) : un
    échec de suppression du dossier est journalisé, pas remonté — la conversation reste supprimée
    en base, seul le nettoyage disque a pu manquer, et il ne doit pas annuler une suppression déjà
    actée.
    """
    from backend.fichiers import supprimer_dossier_conversation

    try:
        supprimer_dossier_conversation(conversation_id)
    except ErreurPersistance as exc:
        logger.error("Suppression du dossier de fichiers de {} échouée : {}", conversation_id, exc)


def lire_reglages(conversation_id: str) -> ReglagesConversation:
    """Réglages de la conversation, ou les valeurs par défaut si aucune ligne n'a été écrite."""
    ligne = fetch_one(
        _LigneReglages,
        "SELECT prompt_systeme, parametres, historique_max_messages, outils_actifs"
        " FROM chat_reglages WHERE conversation_id = ?",
        (conversation_id,),
    )
    if ligne is None:
        return ReglagesConversation()
    return ReglagesConversation(
        prompt_systeme=ligne.prompt_systeme,
        parametres=_decoder_parametres(conversation_id, ligne.parametres),
        historique_max_messages=ligne.historique_max_messages,
        outils_actifs=_decoder_outils(conversation_id, ligne.outils_actifs),
    )


def _decoder_outils(conversation_id: str, document: str | None) -> list[str] | None:
    """Sélection d'outils lue en base. `None` = tous, jamais confondu avec `[]` = aucun.

    Un document illisible retombe sur `None` — tous les outils — plutôt que sur une liste vide :
    une conversation dont le réglage serait corrompu doit rester utilisable, pas se retrouver
    silencieusement privée de tout moyen d'agir.
    """
    if document is None:
        return None
    try:
        valeur = json.loads(document)
    except ValueError as exc:
        logger.warning("Sélection d'outils illisible sur {} ({}) : tous les outils.",
                       conversation_id, exc)
        return None
    if not isinstance(valeur, list):
        return None
    return [str(nom) for nom in valeur]


def _decoder_parametres(conversation_id: str, document: str) -> ParametresEchantillonnage:
    try:
        return ParametresEchantillonnage.model_validate(json.loads(document))
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Paramètres illisibles pour la conversation {} : {}", conversation_id, exc)
        raise ErreurPersistance(
            "Paramètres d'échantillonnage illisibles en base.",
            remediation="Réenregistrer les réglages de cette conversation depuis l'interface.",
            details={"conversation_id": conversation_id, "cause": str(exc)},
        ) from exc


def ecrire_reglages(conversation_id: str, reglages: ReglagesConversation) -> ReglagesConversation:
    """Écrit les réglages complets de la conversation (insertion ou remplacement)."""
    exiger_conversation(conversation_id)
    execute(
        "INSERT INTO chat_reglages (conversation_id, prompt_systeme, parametres,"
        " historique_max_messages, outils_actifs, maj_le) VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(conversation_id) DO UPDATE SET prompt_systeme = excluded.prompt_systeme,"
        " parametres = excluded.parametres, historique_max_messages = excluded.historique_max_messages,"
        " outils_actifs = excluded.outils_actifs, maj_le = excluded.maj_le",
        (
            conversation_id,
            reglages.prompt_systeme,
            reglages.parametres.model_dump_json(),
            reglages.historique_max_messages,
            None if reglages.outils_actifs is None else json.dumps(reglages.outils_actifs),
            maintenant(),
        ),
    )
    return reglages


_SELECT_COMPACTIONS = (
    "SELECT id, conversation_id, message_id, coupe_message_id, nb_messages_resumes,"
    " tokens_avant, tokens_apres, contexte_total, resume, cree_le"
    " FROM chat_compactions WHERE conversation_id = ? ORDER BY cree_le ASC, rowid ASC"
)

_INSERT_COMPACTION = (
    "INSERT INTO chat_compactions (id, conversation_id, message_id, coupe_message_id,"
    " nb_messages_resumes, tokens_avant, tokens_apres, contexte_total, resume, cree_le)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def lire_compactions(conversation_id: str) -> list[InfoCompaction]:
    """Toutes les compactions de la conversation, de la plus ancienne à la plus récente."""
    return fetch_all(InfoCompaction, _SELECT_COMPACTIONS, (conversation_id,))


def _attacher_compactions(conversation_id: str, messages: list[MessageChat]) -> list[MessageChat]:
    """Pose sur chaque message assistant déclencheur la balise de compaction qui lui revient.

    Une seule requête pour toute la conversation : la balise voyage AVEC le message, sans liste
    parallèle à réordonner côté client. Un rechargement montre ainsi exactement ce que le direct a
    montré. Les messages sans compaction sont rendus inchangés.
    """
    compactions = {info.message_id: info for info in lire_compactions(conversation_id)}
    if not compactions:
        return messages
    return [
        message.model_copy(update={"compaction": compactions[message.id]})
        if message.id in compactions
        else message
        for message in messages
    ]


def enregistrer_compaction(info: InfoCompaction) -> None:
    """Persiste une balise de compaction. À appeler APRÈS l'écriture de son message assistant.

    La ligne référence `messages(id)` : le message déclencheur doit exister, sans quoi la clé
    étrangère refuse l'insertion. C'est voulu — une balise sans son message serait un fantôme.
    """
    try:
        execute(
            _INSERT_COMPACTION,
            (
                info.id,
                info.conversation_id,
                info.message_id,
                info.coupe_message_id,
                info.nb_messages_resumes,
                info.tokens_avant,
                info.tokens_apres,
                info.contexte_total,
                info.resume,
                info.cree_le.isoformat(),
            ),
        )
    except sqlite3.Error as exc:
        logger.error("Balise de compaction non persistée sur {} : {}", info.conversation_id, exc)
        raise ErreurPersistance(
            "Écriture de la balise de compaction impossible.", details={"cause": str(exc)}
        ) from exc


def lire_compaction_active(conversation_id: str, chemin_ids: set[str]) -> InfoCompaction | None:
    """La compaction la plus récente dont la coupe est sur le chemin affiché, ou `None`.

    Sur une conversation branchée, plusieurs compactions peuvent exister sur des branches distinctes :
    seule compte celle dont le point de coupe appartient au chemin courant. On prend la plus récente
    parmi celles-là — c'est le résumé cumulatif le plus à jour de cette branche.
    """
    candidates = [
        info for info in lire_compactions(conversation_id) if info.coupe_message_id in chemin_ids
    ]
    return candidates[-1] if candidates else None


def lire_messages_complets(conversation_id: str) -> list[MessageChat]:
    """TOUS les messages de la conversation, branches abandonnées comprises, dans l'ordre d'écriture."""
    return _attacher_compactions(
        conversation_id, fetch_all(MessageChat, _SELECT_MESSAGES, (conversation_id,))
    )


def lister_messages(conversation_id: str) -> list[MessageChat]:
    """Chemin actif : de la racine à la feuille affichée.

    Sur une conversation restée linéaire — toutes celles écrites avant les branches — le chemin
    contient exactement tous les messages, dans le même ordre qu'avant. La signature ne change pas :
    les appelants existants n'ont rien à savoir de l'arbre.
    """
    return lire_branche(conversation_id).messages


def lire_branche(conversation_id: str) -> EtatBranche:
    """Chemin actif, feuille résolue et variantes de chaque message — tout ce qu'affiche l'écran."""
    messages = lire_messages_complets(conversation_id)
    feuille = branches.resoudre_feuille(messages, _feuille_enregistree(conversation_id))
    chemin = branches.chemin_vers(messages, feuille)
    return EtatBranche(
        conversation_id=conversation_id,
        feuille_active=feuille,
        messages=chemin,
        variantes=branches.variantes(messages, chemin),
    )


def lire_arbre(conversation_id: str) -> ArbreConversation:
    """Arbre complet. C'est la preuve lisible qu'un rejeu ou une édition n'efface rien."""
    exiger_conversation(conversation_id)
    messages = lire_messages_complets(conversation_id)
    return ArbreConversation(
        conversation_id=conversation_id,
        feuille_active=branches.resoudre_feuille(messages, _feuille_enregistree(conversation_id)),
        messages=messages,
    )


def _feuille_enregistree(conversation_id: str) -> str | None:
    """Pointeur brut, tel qu'il est en base — non résolu : il peut viser un message disparu."""
    ligne = fetch_one(
        _LigneFeuille,
        "SELECT feuille_id FROM chat_branche_active WHERE conversation_id = ?",
        (conversation_id,),
    )
    return ligne.feuille_id if ligne is not None else None


def feuille_active(conversation_id: str) -> str | None:
    """Feuille réellement affichée. `None` sur une conversation vide — l'appelant décide quoi faire."""
    messages = lire_messages_complets(conversation_id)
    return branches.resoudre_feuille(messages, _feuille_enregistree(conversation_id))


def definir_feuille_active(conversation_id: str, message_id: str | None) -> None:
    """Écrit le pointeur de branche. `None` le remet à la feuille naturelle (la plus récente)."""
    execute(_UPSERT_FEUILLE, (conversation_id, message_id, maintenant()))


def activer_branche(conversation_id: str, message_id: str) -> EtatBranche:
    """Bascule la vue vers la branche qui contient ce message, et rend la nouvelle vue.

    On redescend jusqu'à la feuille la plus récente sous le message choisi : cliquer sur une
    variante doit rouvrir la suite de conversation qu'elle avait produite, pas s'arrêter sur elle.
    """
    exiger_message(conversation_id, message_id)
    messages = lire_messages_complets(conversation_id)
    feuille = branches.descendre(messages, message_id)
    definir_feuille_active(conversation_id, feuille)
    logger.debug("Branche activée sur {} : feuille {}", conversation_id, feuille)
    return lire_branche(conversation_id)


def lire_message(conversation_id: str, message_id: str) -> MessageChat | None:
    """Message de CETTE conversation, ou `None`.

    Le filtre sur la conversation n'est pas cosmétique : sans lui, une route accepterait de rejouer
    dans la conversation A un message appartenant à la conversation B.
    """
    return fetch_one(MessageChat, _SELECT_MESSAGE_UNIQUE, (conversation_id, message_id))


def exiger_message(conversation_id: str, message_id: str) -> MessageChat:
    """Comme `lire_message`, mais lève plutôt que de rendre `None`."""
    message = lire_message(conversation_id, message_id)
    if message is None:
        raise MessageIntrouvable(f"Message inconnu dans cette conversation : {message_id}")
    return message


def chemin_jusqua(conversation_id: str, message_id: str) -> list[MessageChat]:
    """Chemin racine → `message_id` : l'historique exact que verra le moteur pour ce point de l'arbre."""
    return branches.chemin_vers(lire_messages_complets(conversation_id), message_id)


def ajouter_message(
    conversation_id: str,
    role: RoleMessage,
    contenu: str,
    *,
    identifiant: str | None = None,
    modele_id: str | None = None,
    tokens_generes: int | None = None,
    tokens_par_seconde: float | None = None,
    interrompu: bool = False,
    parent_id: str | None = None,
    definir_feuille: bool = True,
) -> MessageChat:
    """Insère un message et remonte l'horodatage de la conversation, en une transaction.

    `identifiant` impose l'id déjà annoncé au client à l'ouverture d'un flux — sans quoi le
    frontend garderait un message fantôme à côté du vrai. `parent_id` est FOURNI par l'appelant,
    jamais deviné ici : lui seul sait s'il prolonge la branche courante ou s'il en ouvre une sœur.
    """
    message = MessageChat(
        id=identifiant or str(uuid.uuid4()),
        conversation_id=conversation_id,
        role=role,
        contenu=contenu,
        tokens_generes=tokens_generes,
        tokens_par_seconde=tokens_par_seconde,
        cree_le=maintenant(),
        modele_id=modele_id,
        interrompu=interrompu,
        parent_id=parent_id,
    )
    _ecrire_message(message, definir_feuille=definir_feuille)
    return message


def _valeurs_message(message: MessageChat, horodatage: str) -> tuple[object, ...]:
    """Valeurs de `_INSERT_MESSAGE`, dans l'ordre exact des colonnes déclarées."""
    return (
        message.id,
        message.conversation_id,
        message.role,
        message.contenu,
        message.tokens_generes,
        message.tokens_par_seconde,
        horodatage,
        message.parent_id,
    )


def _ecrire_message(message: MessageChat, *, definir_feuille: bool) -> None:
    """Écrit le message, ses métadonnées de domaine, l'horodatage et la feuille, en un bloc.

    Les écritures forment une seule transaction : un message sans son horodatage remonté ferait
    descendre la conversation dans la liste alors qu'elle vient de bouger, et une feuille écrite
    sans son message pointerait sur un identifiant inexistant.
    """
    horodatage = message.cree_le.isoformat()
    try:
        with transaction() as conn:
            conn.execute(_INSERT_MESSAGE, _valeurs_message(message, horodatage))
            if message.modele_id is not None or message.interrompu:
                conn.execute(
                    _INSERT_META_MESSAGE, (message.id, message.modele_id, int(message.interrompu))
                )
            conn.execute(
                "UPDATE conversations SET maj_le = ? WHERE id = ?", (horodatage, message.conversation_id)
            )
            if definir_feuille:
                conn.execute(_UPSERT_FEUILLE, (message.conversation_id, message.id, horodatage))
    except sqlite3.Error as exc:
        logger.error("Écriture du message dans {} échouée : {}", message.conversation_id, exc)
        raise ErreurPersistance("Écriture du message impossible.", details={"cause": str(exc)}) from exc


def supprimer_messages(conversation_id: str) -> int:
    """Vide l'historique sans supprimer la conversation ni ses réglages. Retourne le nombre effacé."""
    exiger_conversation(conversation_id)
    supprimes = execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
    # Le pointeur de branche est remis à zéro explicitement : ne dépendre que du ON DELETE SET NULL
    # laisserait une feuille fantôme si les clés étrangères étaient un jour désactivées.
    definir_feuille_active(conversation_id, None)
    execute("UPDATE conversations SET maj_le = ? WHERE id = ?", (maintenant(), conversation_id))
    logger.debug("{} message(s) supprimé(s) dans {}", supprimes, conversation_id)
    return supprimes
