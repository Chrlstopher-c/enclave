"""Garde-fous des commandes du modèle — refuser AVANT exécution ce qui n'a rien à faire dans un atelier.

Ce n'est pas un bac à sable : la frontière dure reste celle du conteneur atelier (il ne voit que son
volume et la racine des projets). Ce module est la seconde ligne, lexicale, qui arrête les accidents
plausibles d'un modèle qui travaille vite :

- détruire hors de son dossier (`rm -rf /`, `rm -rf ..`, `cd / && rm -rf usr`) ;
- toucher le dossier d'un AUTRE projet ou d'une autre conversation ;
- agir vers l'extérieur sans l'utilisateur (`git push`, `npm publish`, `ssh`) ;
- tuer l'atelier lui-même (`pkill python`, `kill 1`) ou la machine (`shutdown`, `mkfs`) ;
- effacer les instantanés qui permettent d'annuler son travail (`.echohub`).

Limite assumée : une indirection (`X=/projets; rm -rf $X/autre`) échappe à une analyse lexicale.
Le filet derrière, ce sont les instantanés git pris avant chaque tour et la frontière du conteneur.
"""

from __future__ import annotations

import posixpath
import re
import shlex

DOSSIER_RESERVE = ".echohub"
# Racines vues DANS l'atelier : y toucher hors de son propre dossier est refusé.
RACINES_PARTAGEES = ("/projets", "/workspace")
# Hors de son dossier, seul le temporaire peut être détruit.
HORS_DOSSIER_DESTRUCTIBLE = ("/tmp",)
SEPARATEURS = frozenset({";", "&&", "||", "|", "&", "\n", "(", ")"})

_REGLES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(motif), raison) for motif, raison in (
        (r"\bmkfs(\.\w+)?\b", "formater un système de fichiers"),
        (r"\bdd\b[^;&|]*\bof=/dev/", "écrire directement sur un périphérique"),
        (r">\s*/dev/(sd|nvme|hd|vd|mmcblk)", "écrire directement sur un disque"),
        (r"(^|[;&|(\s])(shutdown|reboot|halt|poweroff)\b", "arrêter ou redémarrer la machine"),
        (r":\s*\(\s*\)\s*\{", "bombe de processus"),
        (r"(^|[;&|(\s])(killall|pkill)\b", "tuer des processus par nom (l'atelier lui-même en mourrait) — "
                                           "utiliser `serveur_fond` action arreter, ou `kill <pid>`"),
        (r"\bkill\s+(-\w+\s+)*-?1\b", "tuer tous les processus ou le processus 1"),
        (r"\bgit\s+push\b", "publier vers un dépôt distant — c'est à l'utilisateur de le faire"),
        (r"\b(npm|bun|yarn|pnpm|cargo|poetry)\s+publish\b", "publier un paquet — c'est à l'utilisateur de le faire"),
        (r"\btwine\s+upload\b", "publier un paquet — c'est à l'utilisateur de le faire"),
        (r"(^|[;&|(\s])(ssh|scp|sftp|rsync\s[^;&|]*:)\s", "se connecter à une machine distante"),
        (r"(^|[;&|(\s])(systemctl|crontab|docker|mount|umount|chroot)\b",
         "administrer le système hôte (indisponible et hors du périmètre)"),
    )
)

_DRAPEAUX_RECURSIFS = re.compile(r"^-[a-zA-Z]*[rR][a-zA-Z]*$|^--recursive$")
_CIBLES_INTERDITES = frozenset({"/", "/*", "~", "~/", "$HOME", "${HOME}", ".", "./", "*", "./*", ".*", ".."})
_CHEMIN_PYTHON = re.compile(r"""["'](/(?:projets|workspace)(?:/[^"']*)?)["']""")


class CommandeRefusee(Exception):
    """La commande enfreint un garde-fou. Le message part tel quel au modèle."""


def _jetons(commande: str) -> list[str]:
    lexeur = shlex.shlex(commande, posix=True, punctuation_chars=";&|()")
    lexeur.whitespace_split = True
    lexeur.commenters = ""
    try:
        return list(lexeur)
    except ValueError:
        return commande.split()


def _segments(jetons: list[str]) -> list[list[str]]:
    segments: list[list[str]] = [[]]
    for jeton in jetons:
        if jeton in SEPARATEURS or set(jeton) <= set(";&|()"):
            segments.append([])
        else:
            segments[-1].append(jeton)
    return [s for s in segments if s]


def _dedans(chemin: str, racine: str) -> bool:
    return chemin == racine or chemin.startswith(racine.rstrip("/") + "/")


def _resoudre(jeton: str, cwd: str) -> str:
    return posixpath.normpath(jeton if jeton.startswith("/") else posixpath.join(cwd, jeton))


def _verifier_chemin(jeton: str, cwd: str, racine: str) -> None:
    """Un jeton qui désigne un dossier partagé ou remonte au-dessus de la racine doit rester dedans."""
    valeur = jeton.split("=", 1)[1] if jeton.startswith("-") and "=" in jeton else jeton
    if "://" in valeur:
        return
    if DOSSIER_RESERVE in valeur.split("/"):
        raise CommandeRefusee(f"« {DOSSIER_RESERVE} » contient les instantanés du harnais : interdit d'y toucher.")
    absolu = valeur.startswith("/")
    partage = absolu and any(_dedans(posixpath.normpath(valeur), r) for r in RACINES_PARTAGEES)
    if (partage or ".." in valeur.split("/")) and not _dedans(_resoudre(valeur, cwd), racine):
        raise CommandeRefusee(f"« {jeton} » sort de ton dossier de travail ({racine}). Reste dedans.")


def _verifier_destruction(programme: str, args: list[str], cwd: str, racine: str) -> None:
    recursif = any(_DRAPEAUX_RECURSIFS.match(a) for a in args)
    if programme in ("chmod", "chown") and not recursif:
        return
    for cible in (a for a in args if not a.startswith("-")):
        if cible in _CIBLES_INTERDITES and (recursif or cible in ("/", "/*")):
            raise CommandeRefusee(f"`{programme} {cible}` détruirait tout un dossier. Nomme précisément ce "
                                  "que tu supprimes (ex. `rm -rf dist`).")
        absolu = _resoudre(cible, cwd)
        if not _dedans(absolu, racine) and not any(_dedans(absolu, t) for t in HORS_DOSSIER_DESTRUCTIBLE):
            raise CommandeRefusee(f"`{programme}` sur « {cible} » ({absolu}) : hors de ton dossier ({racine}).")


def _programme(segment: list[str]) -> tuple[str, list[str]]:
    i = 0
    while i < len(segment) and (re.match(r"^[A-Za-z_]\w*=", segment[i]) or segment[i] in ("sudo", "env", "nohup",
                                                                                           "time", "exec")):
        i += 1
    if i >= len(segment):
        return "", []
    return posixpath.basename(segment[i]), segment[i + 1:]


def verifier_commande(commande: str, racine: str) -> None:
    """Lève `CommandeRefusee` si `commande`, lancée dans `racine` (chemin vu de l'atelier), enfreint un garde-fou."""
    for motif, raison in _REGLES:
        if motif.search(commande):
            raise CommandeRefusee(f"Commande refusée par le harnais : {raison}.")
    cwd = racine
    for segment in _segments(_jetons(commande)):
        programme, args = _programme(segment)
        for jeton in args:
            _verifier_chemin(jeton, cwd, racine)
        if programme == "cd":
            cwd = _resoudre(args[0], cwd) if args and not args[0].startswith("-") else "/root"
        elif programme in ("rm", "rmdir", "shred", "chmod", "chown", "unlink"):
            _verifier_destruction(programme, args, cwd, racine)


def verifier_code_python(code: str, racine: str) -> None:
    """Version allégée pour du Python : chemins littéraux vers un dossier partagé, dossier réservé."""
    if DOSSIER_RESERVE in code:
        raise CommandeRefusee(f"« {DOSSIER_RESERVE} » contient les instantanés du harnais : interdit d'y toucher.")
    for chemin in _CHEMIN_PYTHON.findall(code):
        if not _dedans(posixpath.normpath(chemin), racine):
            raise CommandeRefusee(f"« {chemin} » sort de ton dossier de travail ({racine}). Reste dedans.")


__all__ = ["CommandeRefusee", "verifier_code_python", "verifier_commande"]
