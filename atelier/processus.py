"""Processus de fond de l'atelier — serveurs de dev, watchers, tout ce qui ne rend pas la main.

Une commande ordinaire (`/executer/commande`) attend la fin du processus : un `bun run dev` ou un
`uvicorn` ne finit jamais, l'appel tombait au délai maximal et le serveur mourait avec lui. Ici le
processus est détaché dans sa propre session (groupe de processus), sa sortie part dans un journal
HORS de l'espace de travail, et on le retrouve par (dossier, nom) pour lire son journal ou l'arrêter.

Bornes : `MAX_PAR_DOSSIER` processus vivants par dossier de travail, journal relu en queue seulement.
L'état est en mémoire : un redémarrage de l'atelier tue les processus de toute façon (même conteneur,
même PID 1), il n'y a donc rien à persister.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

DOSSIER_JOURNAUX = Path("/tmp/echohub-processus")
MAX_PAR_DOSSIER = 5
LIGNES_JOURNAL_MAX = 400


@dataclass
class ProcessusFond:
    nom: str
    dossier: Path
    commande: str
    proc: subprocess.Popen[bytes]
    journal: Path
    debut: float

    def vivant(self) -> bool:
        return self.proc.poll() is None


_PROCESSUS: dict[tuple[str, str], ProcessusFond] = {}


def _cle(dossier: Path, nom: str) -> tuple[str, str]:
    return (str(dossier), nom)


def _queue(journal: Path, lignes: int) -> str:
    try:
        texte = journal.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Journal illisible {} : {}", journal, exc)
        return ""
    return "\n".join(texte.splitlines()[-max(1, min(lignes, LIGNES_JOURNAL_MAX)):])


def _vivants_du_dossier(dossier: Path) -> list[ProcessusFond]:
    return [p for p in _PROCESSUS.values() if p.dossier == dossier and p.vivant()]


def decrire(p: ProcessusFond) -> dict[str, object]:
    return {
        "nom": p.nom,
        "commande": p.commande,
        "pid": p.proc.pid,
        "vivant": p.vivant(),
        "code_retour": p.proc.poll(),
        "depuis_s": round(time.monotonic() - p.debut, 1),
    }


def lancer(dossier: Path, nom: str, commande: str) -> dict[str, object]:
    """Lance `commande` détachée dans `dossier`. Lève ValueError si la borne ou le nom l'interdit."""
    existant = _PROCESSUS.get(_cle(dossier, nom))
    if existant is not None and existant.vivant():
        raise ValueError(f"Un processus « {nom} » tourne déjà ici (pid {existant.proc.pid}). L'arrêter d'abord.")
    if len(_vivants_du_dossier(dossier)) >= MAX_PAR_DOSSIER:
        raise ValueError(f"Borne atteinte : {MAX_PAR_DOSSIER} processus de fond vivants dans ce dossier.")
    DOSSIER_JOURNAUX.mkdir(parents=True, exist_ok=True)
    journal = DOSSIER_JOURNAUX / f"{abs(hash(_cle(dossier, nom)))}.log"
    try:
        with journal.open("wb") as sortie:
            proc = subprocess.Popen(["bash", "-lc", commande], cwd=dossier, stdout=sortie,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    start_new_session=True)
    except OSError as exc:
        logger.error("Lancement de fond impossible ({}) : {}", nom, exc)
        raise ValueError(f"Lancement impossible : {exc}") from exc
    p = ProcessusFond(nom=nom, dossier=dossier, commande=commande, proc=proc, journal=journal,
                      debut=time.monotonic())
    _PROCESSUS[_cle(dossier, nom)] = p
    logger.info("processus de fond « {} » lancé dans {} (pid {})", nom, dossier.name, proc.pid)
    return decrire(p)


def journal(dossier: Path, nom: str, lignes: int) -> dict[str, object]:
    p = _PROCESSUS.get(_cle(dossier, nom))
    if p is None:
        raise KeyError(nom)
    return {**decrire(p), "journal": _queue(p.journal, lignes)}


def arreter(dossier: Path, nom: str) -> dict[str, object]:
    """SIGTERM au groupe, puis SIGKILL après 5 s : un serveur de dev engendre souvent des enfants."""
    p = _PROCESSUS.get(_cle(dossier, nom))
    if p is None:
        raise KeyError(nom)
    if p.vivant():
        try:
            os.killpg(p.proc.pid, signal.SIGTERM)
            p.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(p.proc.pid, signal.SIGKILL)
            p.proc.wait(timeout=5)
        except ProcessLookupError:
            logger.info("processus « {} » déjà terminé", nom)
    logger.info("processus de fond « {} » arrêté dans {}", nom, dossier.name)
    return {**decrire(p), "journal": _queue(p.journal, 40)}


def lister(dossier: Path) -> list[dict[str, object]]:
    return [decrire(p) for p in _PROCESSUS.values() if p.dossier == dossier]
