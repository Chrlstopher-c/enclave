"""Pont vers l'atelier d'exécution — le confinement a quitté le backend pour la frontière d'un conteneur.

Historique. Le code d'un modèle tournait ici même, dans un sous-processus confiné : `setuid` vers
un utilisateur non privilégié, `rlimits`, PATH réduit à `/usr/bin:/bin`. Conséquence mesurée le
2026-08-26 : le modèle voulait `nasm`, réponse `nasm: command not found` — il ne pouvait ni
installer un paquet, ni disposer d'un vrai environnement. Le confinement protégeait l'hôte au prix
de rendre l'outil inerte dès qu'il fallait autre chose que les binaires de base de l'image.

Décision (option B). L'exécution vit désormais dans un conteneur de dev séparé, `echohub-atelier`,
toujours actif, où l'agent est root, a le réseau, un PATH complet et peut faire `apt install`. Un
seul atelier partagé par toutes les conversations, chacune ayant son dossier de travail dans un
volume commun. Le confinement vis-à-vis de la machine de Chris n'a pas disparu : il s'est DÉPLACÉ
de `setuid`+`rlimits` vers la frontière du conteneur — exactement comme un environnement Docker de
dev isole ce qu'on y lance. Ce qui protège l'hôte, c'est que l'atelier ne monte aucun chemin de
l'hôte et voit ses ressources bornées par Compose (`mem_limit`, `cpus`, `pids_limit`).

Ce module ne fait plus tourner de processus : il traduit un `racine_bac` de conversation en un
dossier de l'atelier, délègue à `backend.outils.atelier`, et rend le résultat sous la forme que les
outils connaissent déjà (`ResultatExecution`). Il ne lève jamais : un atelier injoignable devient un
résultat au message actionnable, pas un plantage.

Ce qui reste de l'ancien monde, et sert encore aux outils de fichiers (`ecrire_fichier`,
`lire_fichier`, `lister_fichiers`) : la résolution d'un chemin dans le bac (`resoudre_dans_bac`,
frontière anti-`../`) et la préparation du dossier (`preparer_bac`).
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from pydantic import BaseModel

from backend.agent import PREFIXE as PREFIXE_MAISON
from backend.agent import ecriture_permise
from backend.agent import racine as racine_maison
from backend.core import get_settings
from backend.outils.atelier import (
    AtelierInjoignable,
    Racine,
    ReponseAtelier,
    executer_commande as _executer_commande_atelier,
    executer_python as _executer_python_atelier,
)

# Délais GÉNÉREUX, et c'est voulu : dans l'atelier un `apt install` prend des minutes, un `git
# clone` ou une compilation aussi. L'ancien plafond de quelques secondes tuait précisément ce que
# l'atelier existe pour permettre. Le délai reste borné — une commande folle finit par être tuée —
# mais il laisse le temps d'une vraie installation. L'atelier applique ce délai côté serveur et
# rend un résultat propre ; le client HTTP attend un peu plus (voir `atelier.MARGE_CLIENT_SECONDES`).
TIMEOUT_COMMANDE_SECONDES = 600
# Dossier des instantanés d'un projet (dépôt git séparé), intouchable par le modèle.
DOSSIER_RESERVE = ".echohub"
TIMEOUT_PYTHON_SECONDES = 600

LIMITES_REELLES_TEXTE = (
    "Le code et les commandes s'exécutent dans un ATELIER : un conteneur de développement séparé, "
    "toujours actif, isolé de la machine de l'utilisateur par la frontière du conteneur — comme un "
    "environnement Docker de dev. Dans cet atelier tu es ROOT, tu as un vrai terminal, le réseau, un "
    "PATH complet et les outils de dev (git, gcc, make, python3, node…). Tu peux INSTALLER des "
    "paquets avec « apt-get install » ou « pip install » : ils restent disponibles pour la suite. "
    "Les fichiers et les paquets installés PERSISTENT d'un message à l'autre. Chaque conversation a "
    "son dossier de travail, où atterrissent les fichiers produits — ils deviennent des fichiers de "
    "la conversation. Reste dans ce dossier : ceux des autres conversations et des projets te sont "
    "interdits, et le harnais refuse les commandes destructrices hors de ton dossier ou tournées vers "
    "l'extérieur (git push, publication, ssh). Pour le reste, agis comme sur ta propre machine de dev."
)


class ResultatExecution(BaseModel):
    """Ce que l'atelier a produit — jamais levé en exception, toujours rendu."""

    sortie: str
    erreur: str
    code_retour: int
    duree_s: float
    tue_par_filet_securite: bool


class CheminHorsBac(Exception):
    """Le chemin demandé par le modèle sort du bac de sa conversation."""


def emplacement_atelier(racine_bac: Path) -> tuple[Racine, str]:
    """(racine, sous-dossier) de l'atelier correspondant à `racine_bac`.

    Un bac situé sous la racine des projets (`ECHOHUB_PROJETS_RACINE`) est un PROJET : l'atelier le
    voit sous `/projets/<nom>`. Sinon c'est le dossier de travail d'une conversation.
    """
    projets = get_settings().projets_racine
    if projets is not None:
        try:
            return "projets", str(racine_bac.resolve().relative_to(projets.resolve()))
        except ValueError:
            pass
    return "workspace", _sous_dossier(racine_bac)


def chemin_dans_atelier(racine_bac: Path) -> str:
    """Le dossier de travail tel que le shell de l'atelier le voit — base des garde-fous."""
    racine, sous_dossier = emplacement_atelier(racine_bac)
    return f"/{racine}/{sous_dossier}"


def _sous_dossier(racine_bac: Path) -> str:
    """Dossier de travail de la conversation, RELATIF à la racine partagée avec l'atelier.

    Le backend voit ce dossier sous `settings.atelier_workspace` (p. ex. `/data/ateliers/<id>`) ;
    l'atelier le voit sous `/workspace/<id>` via le même volume. Seul le suffixe commun (`<id>`)
    voyage, jamais un chemin absolu du backend qui n'aurait aucun sens dans l'atelier. Repli sur le
    dernier segment si `racine_bac` n'est pas sous la racine (cas des tests hors conteneur).
    """
    workspace = get_settings().atelier_workspace
    try:
        return str(racine_bac.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return racine_bac.name


def _depuis_reponse(reponse: ReponseAtelier) -> ResultatExecution:
    """Traduit la réponse de l'atelier dans la forme que les outils connaissent."""
    return ResultatExecution(
        sortie=reponse.sortie,
        erreur=reponse.erreur,
        code_retour=reponse.code_retour,
        duree_s=reponse.duree_s,
        tue_par_filet_securite=reponse.tue,
    )


def _repli(exc: AtelierInjoignable) -> ResultatExecution:
    """Atelier injoignable : un résultat en échec dont le message dit quoi faire, jamais un plantage."""
    return ResultatExecution(sortie="", erreur=str(exc), code_retour=-1, duree_s=0.0,
                             tue_par_filet_securite=False)


def preparer_bac(racine_bac: Path) -> None:
    """Crée le dossier de travail de la conversation s'il n'existe pas.

    Le backend et l'atelier sont tous deux root sur ce volume partagé : il n'y a plus de bascule
    d'utilisateur ni de `chown` à faire, l'ancien utilisateur non privilégié n'existe plus. Le
    confinement ne vient plus des droits sur ce dossier mais de la frontière du conteneur atelier.
    """
    try:
        racine_bac.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("Préparation du dossier de bac impossible ({}) : {}", racine_bac, exc)


def _relatif_au_bac(racine_bac: Path, demande: Path) -> Path:
    """Ramène au bac les deux façons dont le modèle nomme son propre dossier.

    Mesuré le 2026-10-01 en mode projet : il écrit `todo-final/main.py` (le nom du projet en tête)
    ou `/projets/todo-final/main.py` (le chemin vu du shell, que le prompt lui donne). Les deux
    désignent sans ambiguïté un fichier du bac ; les refuser lui coûtait un tour, souvent le dernier.
    """
    vu_du_shell = Path(chemin_dans_atelier(racine_bac))
    if demande.is_absolute() and (demande == vu_du_shell or vu_du_shell in demande.parents):
        return demande.relative_to(vu_du_shell)
    parties = demande.parts
    if len(parties) > 1 and parties[0] == racine_bac.name and not (racine_bac / parties[0]).exists():
        return Path(*parties[1:])
    return demande


def resoudre_dans_bac(racine_bac: Path, chemin_demande: str) -> Path:
    """Chemin absolu d'un fichier du bac — ou lève, jamais un chemin approximatif.

    Le modèle choisit librement le nom de ses fichiers : c'est une entrée non fiable. Trois refus,
    et le troisième est le seul qui compte vraiment :

    - chemin vide : rien à résoudre ;
    - chemin absolu : `/etc/passwd` n'est pas un fichier de bac ;
    - chemin qui, UNE FOIS RÉSOLU, sort de la racine. La résolution suit les liens symboliques,
      donc un lien posé vers l'extérieur est attrapé ici — vérifier le texte brut (`..`) ne l'aurait
      pas vu.
    """
    if not chemin_demande.strip():
        raise CheminHorsBac("Aucun chemin fourni.")
    if est_maison(chemin_demande):
        return _resoudre_maison(chemin_demande)
    demande = _relatif_au_bac(racine_bac, Path(chemin_demande))
    if demande.is_absolute():
        raise CheminHorsBac(f"Chemin absolu refusé : « {chemin_demande} ». Utiliser un chemin relatif au bac.")
    if DOSSIER_RESERVE in demande.parts:
        raise CheminHorsBac(f"« {DOSSIER_RESERVE} » est réservé aux instantanés du harnais : chemin refusé.")
    racine = racine_bac.resolve()
    cible = (racine / demande).resolve()
    if cible != racine and racine not in cible.parents:
        raise CheminHorsBac(f"Chemin hors du bac : « {chemin_demande} ».")
    return cible


def est_maison(chemin: str) -> bool:
    """Le chemin vise-t-il la maison partagée de l'agent (`~agent/…`) plutôt que le bac ?"""
    texte = chemin.strip()
    return texte == "~agent" or texte.startswith(PREFIXE_MAISON)


def _resoudre_maison(chemin_demande: str) -> Path:
    """Même confinement que le bac, appliqué à la maison de l'agent."""
    relatif = Path(chemin_demande.strip()[len(PREFIXE_MAISON):] if chemin_demande.strip() != "~agent" else "")
    if relatif.is_absolute():
        raise CheminHorsBac(f"Chemin absolu refusé : « {chemin_demande} ».")
    racine = racine_maison()
    cible = (racine / relatif).resolve()
    if cible != racine and racine not in cible.parents:
        raise CheminHorsBac(f"Chemin hors de ~agent/ : « {chemin_demande} ».")
    return cible


def verifier_ecriture(cible: Path) -> None:
    """Refuse d'écrire dans la maison hors de `memoire/`, `skills/` et `notes/` (SYSTEM.md reste à Chris)."""
    racine = racine_maison()
    if cible != racine and racine not in cible.parents:
        return
    if not ecriture_permise(cible.relative_to(racine)):
        raise CheminHorsBac("Écriture refusée dans ~agent/ : seuls ~agent/memoire/, ~agent/skills/ et "
                            "~agent/notes/ sont modifiables.")


def executer_code_confine(code: str, racine_bac: Path) -> ResultatExecution:
    """Exécute `code` Python dans l'atelier, sous le dossier de travail de la conversation. Ne lève jamais.

    Bloquant (appel HTTP synchrone) : l'appelant (`executer_python.py`) le pousse sur un thread pour
    ne pas geler la boucle asyncio.
    """
    preparer_bac(racine_bac)
    try:
        racine, sous_dossier = emplacement_atelier(racine_bac)
        reponse = _executer_python_atelier(code, sous_dossier, TIMEOUT_PYTHON_SECONDES, racine)
    except AtelierInjoignable as exc:
        return _repli(exc)
    return _depuis_reponse(reponse)


def executer_commande_confinee(commande: str, racine_bac: Path) -> ResultatExecution:
    """Exécute une commande shell dans l'atelier, sous le dossier de travail de la conversation. Ne lève jamais.

    Même atelier, même dossier que le code Python : ce que l'un installe ou écrit, l'autre le voit.
    """
    preparer_bac(racine_bac)
    try:
        racine, sous_dossier = emplacement_atelier(racine_bac)
        reponse = _executer_commande_atelier(commande, sous_dossier, TIMEOUT_COMMANDE_SECONDES, racine)
    except AtelierInjoignable as exc:
        return _repli(exc)
    return _depuis_reponse(reponse)


__all__ = [
    "ResultatExecution",
    "CheminHorsBac",
    "LIMITES_REELLES_TEXTE",
    "TIMEOUT_COMMANDE_SECONDES",
    "TIMEOUT_PYTHON_SECONDES",
    "preparer_bac",
    "resoudre_dans_bac",
    "executer_code_confine",
    "executer_commande_confinee",
]
