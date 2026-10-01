"""Surface fichier du bac : écrire, lire, modifier — sans repasser par du code Python.

Raison d'être, constatée le 2026-08-16 et non supposée. Le seul moyen de produire un fichier était
`executer_python` : le modèle devait donc emballer son contenu dans du source Python, ce qui
l'obligeait à échapper deux fois guillemets et retours à la ligne. Le résultat observé était un
`open("hello.py","w").write("...\\n...\\\"...")` illisible — et surtout, à la MOINDRE erreur, le
modèle réécrivait le fichier ENTIER depuis zéro, parce qu'il n'avait aucun moyen d'en toucher une
partie. Sur une page HTML de 3,6 Kio, chaque correction de virgule coûtait une réémission complète.

Les trois outils forment la boucle de travail attendue :

    ecrire_fichier   -> pose le fichier, contenu brut, aucun échappement
    executer_python  -> le lance (paramètre `fichier`)
    lire_fichier     -> relit l'état RÉEL avant de corriger, plutôt que de se fier à sa mémoire
    modifier_fichier -> remplace un fragment exact, le reste du fichier n'est jamais retouché

`modifier_fichier` exige que le fragment cherché apparaisse EXACTEMENT une fois. Zéro occurrence :
le modèle s'est trompé de texte, il doit relire. Plusieurs : la modification serait ambiguë, et
choisir à sa place produirait une édition au mauvais endroit — silencieuse, donc pire qu'un refus.

Chaque écriture est redéposée dans le magasin de `backend.fichiers`. Sans cela, `presenter_fichier`
montrerait la version d'avant l'édition : le dépôt sert les octets qu'il a enregistrés, pas ceux du
bac. Le magasin garde donc plusieurs versions du même nom, et `resoudre_reference` rend la plus
récente — c'est exactement ce que le modèle vient d'écrire.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from loguru import logger

from backend.core import EchoHubError
from backend.fichiers import deposer_fichier
from backend.outils.bac_a_sable import CheminHorsBac, preparer_bac, resoudre_dans_bac
from backend.outils.contrat import ContexteExecution, DescriptionOutil, EchecOutil, Outil

# Un fichier relu repart dans le contexte du modèle. Au-delà, la fenêtre se remplit d'un seul
# fichier et l'historique de la conversation disparaît. `ResultatOutil.tronque()` s'applique de
# toute façon en aval ; cette borne évite seulement de construire un texte énorme avant d'y arriver.
LONGUEUR_LECTURE_MAX = 6_000

_CHEMIN = {
    "type": "string",
    "description": (
        "Path of the file inside this conversation's sandbox, relative — `app.py`, `src/page.html`. "
        "Required: a call without it does nothing. Absolute paths and paths leaving the sandbox are "
        "refused."
    ),
}

# Synonymes constatés ou attendus pour le chemin. `nom` n'est pas une hypothèse : c'est le nom que
# le modèle a réellement employé le 2026-08-16 en accompagnant un contenu de 12 173 caractères, que
# le harnais a jeté pour ce seul motif. Voir `DescriptionOutil.normaliser`.
_ALIAS_CHEMIN = {
    alias: "chemin"
    for alias in ("nom", "nom_fichier", "fichier", "name", "filename", "file", "file_path", "path")
}


def _echec_arguments(outil: str, requis: dict[str, str], recus: dict[str, Any]) -> str:
    """Échec d'un appel incomplet, rédigé pour être ACTIONNABLE plutôt que seulement exact.

    Trois informations, parce que les trois manquaient dans la formulation précédente et que le
    modèle a rejoué le même appel raté trois tours de suite : ce qui est attendu, ce qu'il a envoyé,
    et le fait que tout doit tenir dans le MÊME appel.

    Rédigé en anglais, comme le socle et pour la même raison mesurée : ces modèles raisonnent en
    anglais (visible dans chaque bloc de raisonnement du transcript) et suivent mieux une consigne
    de forme dans cette langue. Aucune syntaxe de balise n'est montrée — les deux dialectes d'appel
    cohabitent selon le modèle, et imposer celui de l'autre famille casserait un appel qui marchait.
    """
    attendus = "\n".join(f"  {cle} = {aide}" for cle, aide in requis.items())
    envoyes = ", ".join(sorted(recus)) if recus else "nothing"
    return (
        f"Failed: `{outil}` was called without everything it needs.\n"
        f"Required arguments, all in the SAME call:\n{attendus}\n"
        f"You sent: {envoyes}.\n"
        "Re-send the call once, with every argument and its full value inline. There is no way to "
        "supply an argument afterwards, and repeating the same incomplete call will fail again."
    )


def _enregistrer(contexte: ContexteExecution, chemin_relatif: str, cible: Path) -> str:
    """Redépose le fichier dans le magasin et rend la mention à afficher au modèle.

    Un échec de dépôt (quota, type MIME hors liste blanche) n'annule pas l'écriture : le fichier
    existe bel et bien dans le bac et le code confiné peut s'en servir. On le dit, sans transformer
    un refus d'affichage en échec d'écriture.
    """
    if contexte.projet is not None:
        return f"Fichier du projet « {contexte.projet} »."
    type_mime = _type_mime_devine(chemin_relatif, cible)
    try:
        fichier = deposer_fichier(
            contexte.conversation_id,
            nom_fourni=chemin_relatif,
            type_mime_declare=type_mime,
            octets=cible.read_bytes(),
            origine="modele",
        )
    except EchoHubError as exc:
        logger.warning("Fichier {} écrit mais non déposé dans le magasin : {}", chemin_relatif, exc)
        return "Non présentable dans la conversation (refusé par le magasin), mais bien présent dans le bac."
    return f"Déposé dans la conversation sous « {fichier.nom_affiche} » (id {fichier.id})."


# Extensions de code source que `mimetypes` ne connaît pas, et qui finissaient donc en fichiers
# INACCESSIBLES à l'utilisateur. Mesuré le 2026-08-26 : le modèle écrit `hello_x86_64.s`,
# `hello_arm64.S`, `hello_mips.s` — les trois sont bien créés dans le bac, et les trois sont refusés
# par le magasin avec « Type MIME refusé : (absent) ». Rien ne remonte dans la conversation ;
# l'utilisateur voit un travail annoncé comme fait et n'a aucun fichier.
#
# Ce ne sont pas des types exotiques : `.s` est de l'assembleur, `.rs` du Rust, `.ts` du TypeScript.
# `mimetypes` s'appuie sur la table du système, qui ne les couvre pas.
_EXTENSIONS_TEXTE = frozenset({
    ".s", ".asm", ".c", ".h", ".cpp", ".hpp", ".cc", ".rs", ".go", ".java", ".kt", ".rb", ".php",
    ".ts", ".tsx", ".jsx", ".sh", ".bash", ".zsh", ".sql", ".toml", ".ini", ".cfg", ".conf",
    ".yml", ".yaml", ".env", ".lua", ".r", ".jl", ".swift", ".m", ".pl", ".vim", ".dockerfile",
    ".gitignore", ".log", ".diff", ".patch", ".tex", ".rst", ".proto", ".gradle", ".make", ".mk",
})

# Au-delà de quoi on cesse de vérifier que le contenu est du texte : lire 64 Kio suffit à trancher,
# et un fichier binaire trahit sa nature dès ses premiers octets.
_ECHANTILLON_TEXTE = 64 * 1024


def _type_mime_devine(chemin_relatif: str, cible: Path) -> str | None:
    """Type MIME du fichier produit — deviné par extension, puis par le CONTENU en dernier recours.

    Le magasin refuse tout type absent de sa liste blanche, ce qui est la bonne règle pour un envoi
    venu de l'extérieur. Mais ce fichier-ci, c'est le bac qui vient de l'écrire : la question n'est
    pas « puis-je faire confiance à cette source ? » mais « ce contenu est-il affichable ? ». Un
    fichier de texte refusé pour une extension inconnue est une perte sèche pour l'utilisateur.

    Le contenu tranche, pas le nom : l'extension oriente, la lecture confirme. Un binaire sans
    extension connue reste refusé, et c'est voulu.
    """
    suffixe = Path(chemin_relatif).suffix.lower()
    # La table d'extensions PRIME sur `mimetypes`, qui ne se contente pas d'ignorer ces fichiers :
    # il leur invente des types absurdes, tout aussi absents de la liste blanche du magasin —
    # `.rs` -> `application/rls-services+xml`, `.ts` -> `text/vnd.trolltech.linguist` (vérifié).
    # Se contenter de compléter `mimetypes` n'aurait donc réparé que `.s`.
    if suffixe in _EXTENSIONS_TEXTE or not suffixe:
        return "text/plain" if _est_du_texte(cible) else None
    type_mime, _ = mimetypes.guess_type(chemin_relatif)
    if type_mime is not None:
        return type_mime
    return "text/plain" if _est_du_texte(cible) else None


def _est_du_texte(cible: Path) -> bool:
    """Le contenu se décode-t-il en UTF-8 ? Un fichier illisible rend False, jamais une exception."""
    try:
        cible.read_bytes()[:_ECHANTILLON_TEXTE].decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return True


def _preparer_cible(contexte: ContexteExecution, chemin_demande: str) -> Path:
    """Résout le chemin dans le bac et crée les dossiers parents. Lève `CheminHorsBac` si hors bac."""
    preparer_bac(contexte.racine_bac)
    cible = resoudre_dans_bac(contexte.racine_bac, chemin_demande)
    cible.parent.mkdir(parents=True, exist_ok=True)
    return cible


# --- ecrire_fichier ----------------------------------------------------------------------------

DESCRIPTION_ECRIRE = DescriptionOutil(
    nom="ecrire_fichier",
    description=(
        "Writes a file into this conversation's sandbox, creating it or overwriting it entirely. "
        "Pass the content RAW — no Python quoting, no escaping. This is how you create any file you "
        "intend to run, show, or edit afterwards. To change part of an existing file, use "
        "`modifier_fichier` instead: never rewrite a whole file to fix a few lines."
    ),
    parametres={
        "type": "object",
        "properties": {
            "chemin": _CHEMIN,
            "contenu": {
                "type": "string",
                "description": "The full text to write. Required: a call without it does nothing.",
            },
        },
        "required": ["chemin", "contenu"],
    },
    alias={**_ALIAS_CHEMIN, "content": "contenu", "texte": "contenu", "text": "contenu", "body": "contenu"},
)

_REQUIS_ECRIRE = {
    "chemin": "the file name, e.g. page.html",
    "contenu": "the full text of the file",
}


async def _ecrire(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
    chemin_demande = str(arguments.get("chemin", "")).strip()
    contenu = arguments.get("contenu")
    # Les deux manques sont signalés par le MÊME message, qui liste les deux arguments. Auparavant
    # chacun avait le sien : le modèle corrigeait celui qu'on lui nommait et omettait l'autre, ce
    # qui produisait deux échecs successifs là où un seul appel complet suffisait.
    if contenu is None or not chemin_demande:
        raise EchecOutil(_echec_arguments("ecrire_fichier", _REQUIS_ECRIRE, arguments))
    try:
        cible = _preparer_cible(contexte, chemin_demande)
    except CheminHorsBac as exc:
        raise EchecOutil(f"Échec : {exc}") from exc
    octets = str(contenu).encode("utf-8")
    cible.write_bytes(octets)
    mention = _enregistrer(contexte, chemin_demande, cible)
    lignes = str(contenu).count("\n") + 1
    return f"Écrit « {chemin_demande} » ({len(octets)} octets, {lignes} lignes). {mention}"


# --- lire_fichier ------------------------------------------------------------------------------

DESCRIPTION_LIRE = DescriptionOutil(
    nom="lire_fichier",
    description=(
        "Reads back a file from this conversation's sandbox, exactly as it stands on disk. Use it "
        "before editing: `modifier_fichier` needs the exact current text, and your memory of what "
        "you wrote is not the file. Also use it after an error, to see the real state rather than "
        "guessing."
    ),
    parametres={
        "type": "object",
        "properties": {
            "chemin": _CHEMIN,
            "ligne_debut": {
                "type": "integer",
                "description": "Optional 1-based line to start from, to read a long file in pieces.",
            },
        },
        "required": ["chemin"],
    },
    alias=dict(_ALIAS_CHEMIN),
)


def _depuis_ligne(texte: str, ligne_debut: object) -> tuple[str, str]:
    """Texte à partir de `ligne_debut` (1-based) et l'en-tête qui situe l'extrait. Sans valeur : tout."""
    try:
        debut = max(1, int(str(ligne_debut))) if ligne_debut not in (None, "") else 1
    except ValueError:
        debut = 1
    if debut == 1:
        return texte, ""
    lignes = texte.splitlines(keepends=True)
    return "".join(lignes[debut - 1:]), f"[à partir de la ligne {debut} sur {len(lignes)}]\n"


async def _lire(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
    chemin_demande = str(arguments.get("chemin", "")).strip()
    if not chemin_demande:
        raise EchecOutil(_echec_arguments("lire_fichier", {"chemin": "the file name to read back"}, arguments))
    try:
        cible = resoudre_dans_bac(contexte.racine_bac, chemin_demande)
    except CheminHorsBac as exc:
        raise EchecOutil(f"Échec : {exc}") from exc
    if not cible.is_file():
        raise EchecOutil(f"Échec : « {chemin_demande} » n'existe pas dans le bac de cette conversation.")
    try:
        texte = cible.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EchecOutil(f"Échec : « {chemin_demande} » illisible en texte ({exc}).") from exc
    texte, entete = _depuis_ligne(texte, arguments.get("ligne_debut"))
    if len(texte) > LONGUEUR_LECTURE_MAX:
        coupe = texte[:LONGUEUR_LECTURE_MAX]
        suite = coupe.count("\n") + 1
        return (f"{entete}{coupe}\n\n[lecture tronquée à {LONGUEUR_LECTURE_MAX} caractères sur {len(texte)} — "
                f"relire la suite avec `ligne_debut` (≈ {suite} lignes lues)]")
    return f"{entete}{texte}"


# --- modifier_fichier --------------------------------------------------------------------------

DESCRIPTION_MODIFIER = DescriptionOutil(
    nom="modifier_fichier",
    description=(
        "Replaces one exact fragment inside an existing sandbox file, leaving everything else "
        "untouched. This is the tool to fix an error: change the few lines that are wrong instead "
        "of rewriting the whole file. The fragment must appear EXACTLY once — read the file first "
        "with `lire_fichier` and copy the text verbatim, including its indentation."
    ),
    parametres={
        "type": "object",
        "properties": {
            "chemin": _CHEMIN,
            "ancien": {
                "type": "string",
                "description": (
                    "The exact text to replace, copied verbatim from the file, including "
                    "indentation and line breaks. Must occur exactly once. Required."
                ),
            },
            "nouveau": {
                "type": "string",
                "description": "The text to put in its place. Required — use an empty string to delete.",
            },
        },
        "required": ["chemin", "ancien", "nouveau"],
    },
    alias={
        **_ALIAS_CHEMIN,
        "old": "ancien",
        "old_string": "ancien",
        "ancien_texte": "ancien",
        "new": "nouveau",
        "new_string": "nouveau",
        "nouveau_texte": "nouveau",
        "remplacement": "nouveau",
    },
)

_REQUIS_MODIFIER = {
    "chemin": "the file to edit",
    "ancien": "the exact text to replace, copied verbatim from the file",
    "nouveau": "the text to put in its place (empty string to delete)",
}


def _verdict_occurrences(nombre: int, ancien: str) -> str | None:
    """Message d'échec quand le fragment n'est pas trouvable exactement une fois, sinon `None`."""
    if nombre == 1:
        return None
    extrait = ancien[:80].replace("\n", "⏎")
    if nombre == 0:
        return (
            f"Échec : le fragment « {extrait} » n'apparaît pas dans le fichier. "
            "Relire le fichier avec `lire_fichier` et recopier le texte exact."
        )
    return (
        f"Échec : le fragment « {extrait} » apparaît {nombre} fois. "
        "Choisir dans quelle occurrence intervenir est impossible — allonger le fragment pour "
        "qu'il devienne unique, en incluant les lignes qui l'entourent."
    )


async def _modifier(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
    chemin_demande = str(arguments.get("chemin", "")).strip()
    ancien = arguments.get("ancien")
    nouveau = arguments.get("nouveau")
    if not ancien or nouveau is None or not chemin_demande:
        raise EchecOutil(_echec_arguments("modifier_fichier", _REQUIS_MODIFIER, arguments))
    try:
        cible = resoudre_dans_bac(contexte.racine_bac, chemin_demande)
    except CheminHorsBac as exc:
        raise EchecOutil(f"Échec : {exc}") from exc
    if not cible.is_file():
        raise EchecOutil(f"Échec : « {chemin_demande} » n'existe pas. Le créer d'abord avec `ecrire_fichier`.")
    try:
        texte = cible.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EchecOutil(f"Échec : « {chemin_demande} » illisible en texte ({exc}).") from exc
    refus = _verdict_occurrences(texte.count(str(ancien)), str(ancien))
    if refus is not None:
        raise EchecOutil(refus)
    cible.write_text(texte.replace(str(ancien), str(nouveau), 1), encoding="utf-8")
    mention = _enregistrer(contexte, chemin_demande, cible)
    return f"Modifié « {chemin_demande} » : un fragment remplacé, le reste du fichier est intact. {mention}"


OUTIL_ECRIRE = Outil(description=DESCRIPTION_ECRIRE, executer=_ecrire)
OUTIL_LIRE = Outil(description=DESCRIPTION_LIRE, executer=_lire)
OUTIL_MODIFIER = Outil(description=DESCRIPTION_MODIFIER, executer=_modifier)

__all__ = ["OUTIL_ECRIRE", "OUTIL_LIRE", "OUTIL_MODIFIER"]
