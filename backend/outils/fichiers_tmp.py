"""`/tmp` pour les outils de fichiers : le brouillon que tout agent s'attend à avoir.

Photo de Chris du 2026-11-10 : `ecrire_fichier /tmp/explore.py` refusé (« chemin absolu »), puis le
modèle a réécrit son script ailleurs et s'est perdu dans ses chemins. `/tmp` est celui de l'ATELIER (là
où le shell tourne) : les outils de fichiers y passent donc par l'atelier, pour que `python /tmp/x.py`
trouve bien ce que `write_file` vient d'y poser.
"""

from __future__ import annotations

import asyncio
import base64
import posixpath

from loguru import logger

from backend.outils.bac_a_sable import executer_code_confine
from backend.outils.contrat import ContexteExecution, EchecOutil

RACINE_TMP = "/tmp"


def est_tmp(chemin: str) -> bool:
    normal = posixpath.normpath(chemin.strip()) if chemin.strip() else ""
    return normal.startswith(RACINE_TMP + "/")


def _chemin(chemin: str) -> str:
    normal = posixpath.normpath(chemin.strip())
    if not est_tmp(normal):
        raise EchecOutil(f"Failed: « {chemin} » is not under /tmp.")
    return normal


async def _executer(code: str, contexte: ContexteExecution) -> str:
    resultat = await asyncio.to_thread(executer_code_confine, code, contexte.racine_bac)
    if resultat.code_retour != 0:
        logger.info("Accès /tmp en échec : {}", resultat.erreur.strip()[-300:])
        raise EchecOutil(f"Failed: {resultat.erreur.strip().splitlines()[-1] if resultat.erreur.strip() else 'error'}")
    return resultat.sortie


async def lire_tmp(chemin: str, contexte: ContexteExecution) -> str:
    """Texte d'un fichier de `/tmp` de l'atelier. Lève `EchecOutil` s'il manque."""
    cible = _chemin(chemin)
    code = ("import base64,sys,os\n"
            f"p={cible!r}\n"
            "if not os.path.isfile(p): sys.exit(f'{p} does not exist')\n"
            "sys.stdout.write(base64.b64encode(open(p,'rb').read()).decode())\n")
    sortie = await _executer(code, contexte)
    try:
        return base64.b64decode(sortie.strip()).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise EchecOutil(f"Failed: « {chemin} » is not readable as text ({exc}).") from exc


async def ecrire_tmp(chemin: str, texte: str, contexte: ContexteExecution) -> int:
    """Écrit `texte` dans `/tmp` de l'atelier (dossiers créés) ; rend le nombre d'octets."""
    cible = _chemin(chemin)
    octets = texte.encode("utf-8")
    charge = base64.b64encode(octets).decode()
    code = ("import base64,os\n"
            f"p={cible!r}\n"
            "os.makedirs(os.path.dirname(p),exist_ok=True)\n"
            f"open(p,'wb').write(base64.b64decode({charge!r}))\n")
    try:
        await _executer(code, contexte)
    except EchecOutil:
        logger.info("Écriture /tmp refusée : {}", cible)
        raise
    return len(octets)


__all__ = ["ecrire_tmp", "est_tmp", "lire_tmp"]
