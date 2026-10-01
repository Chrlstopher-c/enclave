"""Cycle de vie du sous-processus vLLM : interpréteur, démarrage, sonde de santé, arrêt vérifié.

Séparé de l'adaptateur parce que ce sont deux responsabilités distinctes : ici on gère un
processus système, là on parle à une API. Trois décisions structurantes :

- **Attente réelle, jamais de délai fixe.** On sonde `/health` jusqu'à réponse, en surveillant à
  chaque tour que le processus est toujours vivant. Un `sleep(60)` déclare prêt un moteur mort et
  fait perdre le vrai message d'erreur, qui est dans le journal du sous-processus.
- **Arrêt de l'arbre entier.** vLLM lance des workers ; tuer le seul parent laisse la VRAM prise.
- **Aucun `kill` par motif de commande.** Un PID hérité n'est tué qu'après avoir vérifié que sa
  ligne de commande est bien la nôtre : un motif générique (`python`, `vllm`) tuerait un processus
  tiers de la même machine.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import IO, Any

import httpx
import psutil
from loguru import logger

from backend.core import get_settings
from backend.inference.engines_adapters.contrat import CauseEchec, PlanChargement
from backend.inference.engines_adapters.diagnostic import Diagnostic, EchecChargement

PORT_VLLM_DEFAUT = 37823
MODULE_SERVEUR = "vllm.entrypoints.openai.api_server"

# Bornes du démarrage : vLLM compile ses graphes CUDA au premier chargement, plusieurs minutes sont
# normales. Au-delà, ce n'est plus de la lenteur — le processus est bloqué et doit être tué.
INTERVALLE_SONDE_S = 2.0
TENTATIVES_SONDE_MAX = 300
DELAI_SONDE_HTTP_S = 3.0

DELAI_ARRET_S = 10.0

_NOM_FICHIER_PID = "vllm.pid"
_NOM_FICHIER_LOG = "vllm.log"


def port_vllm() -> int:
    """Port dédié au serveur vLLM. Surchargeable pour cohabiter avec une instance externe."""
    brut = os.environ.get("ECHOHUB_VLLM_PORT", "")
    try:
        return int(brut) if brut else PORT_VLLM_DEFAUT
    except ValueError:
        logger.warning("ECHOHUB_VLLM_PORT illisible ({}), retour au port {}", brut, PORT_VLLM_DEFAUT)
        return PORT_VLLM_DEFAUT


def url_base() -> str:
    return f"http://127.0.0.1:{port_vllm()}"


def chemin_journal() -> Path:
    """Journal du sous-processus, remis à zéro à chaque démarrage comme le reste des logs."""
    parametres = get_settings()
    parametres.preparer_repertoires()
    return parametres.logs_dir / _NOM_FICHIER_LOG


def _chemin_pid() -> Path:
    return get_settings().data_dir / _NOM_FICHIER_PID


def _candidats_interpreteur() -> list[Path]:
    """Emplacements où le domaine `engines` installe le venv vLLM, layouts POSIX et Windows.

    vLLM vit dans un venv séparé : ses dépendances (torch, CUDA 13) entrent en conflit avec celles
    du backend. Le chemin peut être imposé par `ECHOHUB_VLLM_PYTHON` quand l'installation est ailleurs.
    """
    impose = os.environ.get("ECHOHUB_VLLM_PYTHON", "")
    if impose:
        return [Path(impose)]
    racine = get_settings().engines_dir / "vllm"
    return [
        racine / dossier / binaire
        for dossier in (".venv", "venv")
        for binaire in (Path("bin") / "python", Path("Scripts") / "python.exe")
    ]


def resoudre_interpreteur() -> Path:
    """Interpréteur du venv vLLM, ou échec qualifié « moteur absent » — jamais un fallback muet."""
    candidats = _candidats_interpreteur()
    for candidat in candidats:
        try:
            if candidat.is_file():
                return candidat
        except OSError as exc:  # chemin réseau ou volume démonté
            logger.warning("Interpréteur {} inspectable : {}", candidat, exc)
    raise EchecChargement(
        Diagnostic(
            cause=CauseEchec.MOTEUR_ABSENT,
            message="Aucun environnement vLLM installé n'a été trouvé.",
            remediation="Installer vLLM depuis l'écran Système, ou pointer ECHOHUB_VLLM_PYTHON sur son interpréteur.",
            indices={"candidats": [str(chemin) for chemin in candidats]},
        )
    )


def construire_commande(plan: PlanChargement, interpreteur: Path) -> list[str]:
    """Traduit le plan en ligne de commande vLLM.

    `batch` du plan n'est délibérément pas transmis : il dimensionne le prompt processing de
    llama.cpp, alors que vLLM gère son propre lotissement continu. Le transmettre reviendrait à
    appliquer une valeur calculée pour un autre moteur.
    """
    if plan.fraction_vram is None:
        raise EchecChargement(
            Diagnostic(
                cause=CauseEchec.PLAN_INCOMPLET,
                message="Le plan vLLM ne fixe pas la fraction de VRAM à préallouer.",
                remediation="Le planificateur doit fournir `fraction_vram` : le défaut vLLM (0,9) "
                            "est intenable sur 16 Go partagés avec le bureau.",
            )
        )
    commande = [
        str(interpreteur), "-m", MODULE_SERVEUR,
        "--model", plan.chemin_modele,
        "--served-model-name", plan.nom_affiche,
        "--host", "127.0.0.1",
        "--port", str(port_vllm()),
        "--max-model-len", str(plan.contexte),
        "--gpu-memory-utilization", str(plan.fraction_vram),
    ]
    if plan.mode_eager:
        commande.append("--enforce-eager")
    return commande


def demarrer(commande: list[str], variables_env: dict[str, str], journal: IO[Any]) -> subprocess.Popen[bytes]:
    """Lance le serveur. Session détachée sous POSIX pour que l'arbre entier soit maîtrisable."""
    environnement = {**os.environ, **variables_env}
    options: dict[str, Any] = {}
    if sys.platform != "win32":
        options["start_new_session"] = True
    try:
        return subprocess.Popen(  # noqa: S603 - commande construite à partir du plan, pas d'une entrée libre
            commande, stdout=journal, stderr=subprocess.STDOUT, env=environnement, **options
        )
    except OSError as exc:
        logger.error("Démarrage du sous-processus vLLM impossible : {}", exc)
        raise EchecChargement(
            Diagnostic(
                cause=CauseEchec.MOTEUR_ABSENT,
                message=f"Le serveur vLLM n'a pas pu être lancé : {exc}",
                remediation="Vérifier l'installation du venv vLLM depuis l'écran Système.",
                indices={"commande": commande[:3]},
            )
        ) from exc


async def attendre_sante(
    processus: subprocess.Popen[bytes],
    *,
    annulation: asyncio.Event | None = None,
    tentatives_max: int = TENTATIVES_SONDE_MAX,
    intervalle_s: float = INTERVALLE_SONDE_S,
) -> tuple[bool, str]:
    """Sonde `/health` jusqu'à réponse, mort du processus, annulation ou épuisement des tentatives.

    Retourne (prêt, raison). La raison sert au diagnostic : elle distingue un moteur mort d'un
    moteur trop lent, deux causes qui appellent des dégradations différentes.
    """
    cible = f"{url_base()}/health"
    async with httpx.AsyncClient(timeout=DELAI_SONDE_HTTP_S) as client:
        for tentative in range(1, tentatives_max + 1):
            if annulation is not None and annulation.is_set():
                return False, "annulation demandée pendant l'attente de démarrage"
            code_sortie = processus.poll()
            if code_sortie is not None:
                return False, f"le processus vLLM s'est arrêté (code {code_sortie})"
            try:
                reponse = await client.get(cible)
                if reponse.status_code == 200:
                    logger.info("vLLM prêt après {} sondage(s)", tentative)
                    return True, ""
            except httpx.HTTPError:
                pass  # serveur pas encore en écoute : c'est le cas normal des premiers tours
            await asyncio.sleep(intervalle_s)
    return False, f"aucune réponse de /health après {tentatives_max * intervalle_s:.0f} s"


def _tuer_arbre(processus: psutil.Process, delai_s: float) -> None:
    """Termine le processus et ses workers, puis force ce qui résiste. Deux attentes bornées."""
    try:
        cibles = [*processus.children(recursive=True), processus]
    except psutil.NoSuchProcess:
        return
    for cible in cibles:
        try:
            cible.terminate()
        except psutil.NoSuchProcess:
            continue
    _, survivants = psutil.wait_procs(cibles, timeout=delai_s)
    for survivant in survivants:
        logger.warning("Processus vLLM {} résiste à terminate, kill", survivant.pid)
        try:
            survivant.kill()
        except psutil.NoSuchProcess:
            continue
    psutil.wait_procs(survivants, timeout=delai_s)


async def arreter(processus: subprocess.Popen[bytes] | None, *, delai_s: float = DELAI_ARRET_S) -> None:
    """Arrête le serveur et son arbre. La VRAM de vLLM n'est rendue qu'à la mort du processus."""
    if processus is None or processus.poll() is not None:
        oublier_pid()
        return
    try:
        cible = psutil.Process(processus.pid)
    except psutil.NoSuchProcess:
        oublier_pid()
        return
    debut = time.perf_counter()
    await asyncio.to_thread(_tuer_arbre, cible, delai_s)
    logger.info("Sous-processus vLLM arrêté en {:.1f} s", time.perf_counter() - debut)
    oublier_pid()


def retenir_pid(pid: int) -> None:
    """Trace le PID sur disque : un backend tué net doit pouvoir nettoyer au redémarrage suivant."""
    try:
        chemin = _chemin_pid()
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(str(pid), encoding="utf-8")
    except OSError as exc:
        logger.warning("PID vLLM non enregistré : {}", exc)


def oublier_pid() -> None:
    try:
        _chemin_pid().unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Fichier PID vLLM non supprimé : {}", exc)


def _est_notre_serveur(processus: psutil.Process) -> bool:
    """Confirme l'identité par la ligne de commande complète, jamais par un nom de binaire."""
    try:
        ligne = " ".join(processus.cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    return MODULE_SERVEUR in ligne and f"--port {port_vllm()}" in ligne


async def nettoyer_orphelin() -> bool:
    """Tue un serveur vLLM hérité d'un backend précédent. Retourne True si un processus a été tué."""
    chemin = _chemin_pid()
    try:
        if not chemin.exists():
            return False
        pid = int(chemin.read_text(encoding="utf-8").strip())
        processus = psutil.Process(pid)
    except (OSError, ValueError, psutil.NoSuchProcess) as exc:
        logger.debug("Aucun orphelin vLLM exploitable : {}", exc)
        oublier_pid()
        return False
    if not _est_notre_serveur(processus):
        logger.warning("PID {} n'est pas notre serveur vLLM : laissé intact", pid)
        oublier_pid()
        return False
    logger.warning("Serveur vLLM orphelin (PID {}) trouvé au démarrage : arrêt", pid)
    await asyncio.to_thread(_tuer_arbre, processus, DELAI_ARRET_S)
    oublier_pid()
    return True
