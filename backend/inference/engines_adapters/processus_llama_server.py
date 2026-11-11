"""Pilotage du sous-processus `llama-server` — le serveur natif de llama.cpp.

POURQUOI CE MOTEUR EXISTE À CÔTÉ DE `llama-cpp-python`. Mesuré le 2026-08-26 sur le 35B-A3B, en
conversation qui s'allonge — l'usage réel, pas un banc :

    llama-cpp-python   tour 1 : 1162 tokens réévalués · tour 2 : 1188 · tour 3 : 1211 · tour 4 : 1228
                       TTFT 5,94 s À CHAQUE MESSAGE d'une même conversation
    llama-server       TTFT 5,96 s au premier message, puis 0,15 s

Le journal de llama.cpp dit la cause mot pour mot :

    Llama.generate: 1161 prefix-match found but partial kv removal not supported,
                    re-evaluating full prompt

Le préfixe EST trouvé. C'est `kv_cache_seq_rm` qui refuse : sur une architecture hybride — un bloc
sur quatre porte un cache KV, les autres un état récurrent — un état récurrent ne se tronque pas.
Or enchaîner un tour sur le précédent demande de retirer les quelques tokens de fin de génération.
`swa_full=True`, le seul réglage des bindings qui touche ce mécanisme, a été essayé : sans effet.
Ce n'est donc pas un paramètre mal réglé, c'est une limite du chemin `llama-cpp-python`.

SECOND BÉNÉFICE, non recherché mais réel : le déport d'experts passe ici par `--override-tensor`,
un argument documenté. Le chemin bindings l'obtient en écrivant à la main dans le champ C
`tensor_buft_overrides` par ctypes, avec trois gardes ABI (`experts_hote.py`) — du travail sérieux,
mais qui n'a plus lieu d'être quand l'argument existe.

CE MODULE NE DÉCIDE DE RIEN : il traduit un plan en ligne de commande, lance, sonde, arrête. Le
placement, le contexte, le type de cache viennent tous du planificateur.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import IO, Any

import httpx
import psutil
from loguru import logger

from backend.inference.engines_adapters.contrat import CauseEchec, PlanChargement
from backend.inference.engines_adapters.diagnostic import Diagnostic, EchecChargement

# Port distinct de celui de vLLM (8000 par défaut chez eux) et de l'API : trois serveurs peuvent
# coexister sur cette machine, et un port partagé produirait un « address already in use » attribué
# au mauvais moteur.
PORT_DEFAUT = 8081
VARIABLE_PORT = "ECHOHUB_PORT_LLAMA_SERVER"

# Emplacement du binaire dans l'image. Compilé pour la seule architecture de la carte cible : le
# binaire de `ghcr.io/ggml-org/llama.cpp` ne peut PAS être copié tel quel — il est lié à la glibc
# d'Ubuntu 24.04 alors que cette image est sur 22.04 (mesuré : « GLIBC_2.38 not found »).
CHEMIN_BINAIRE = Path(os.environ.get("ECHOHUB_LLAMA_SERVER", "/opt/llama-server/llama-server"))

DELAI_SONDE_HTTP_S = 3.0
INTERVALLE_SONDE_S = 2.0
TENTATIVES_SONDE_MAX = 150  # 5 min : un 35B avec experts en RAM met plusieurs minutes à charger
DELAI_ARRET_DOUX_S = 10.0


def port() -> int:
    """Port d'écoute, surchargeable pour faire cohabiter deux instances."""
    brut = os.environ.get(VARIABLE_PORT, "")
    try:
        valeur = int(brut)
    except ValueError:
        return PORT_DEFAUT
    return valeur if 1 <= valeur <= 65535 else PORT_DEFAUT


def url_base() -> str:
    return f"http://127.0.0.1:{port()}"


def binaire_disponible() -> bool:
    """Le binaire est-il présent et exécutable ? Sondé, jamais supposé."""
    chemin = resoudre_binaire()
    return chemin is not None


def resoudre_binaire() -> Path | None:
    """Chemin du binaire, ou None. `PATH` sert de repli pour une installation système."""
    if CHEMIN_BINAIRE.is_file() and os.access(CHEMIN_BINAIRE, os.X_OK):
        return CHEMIN_BINAIRE
    trouve = shutil.which("llama-server")
    return Path(trouve) if trouve else None


# `--reasoning-format none` laisse les balises de réflexion DANS le contenu, telles que le gabarit
# du modèle les produit. C'est le comportement exact du chemin bindings, et c'est ce que le frontend
# sait lire (`chat/raisonnement/extraction.ts` cherche `<think>` dans le texte).
#
# Le défaut `auto` extrait les pensées vers `message.reasoning_content` et les RETIRE du contenu :
# le frontend ne voit alors plus de balise, et la réflexion — en anglais — coule dans la réponse
# sans séparation. Constaté en production le 2026-08-26, capture à l'appui, dès le premier échange
# servi par ce chemin. Un canal séparé n'est pas une amélioration tant que les deux chemins doivent
# produire la même chose.
ARGUMENTS_REFLEXION = ("--reasoning-format", "none")


# Points de reprise du cache, un par tour d'agent. Mesuré le 2026-11-11 (MoE 35B hybride, journal llama-server) : chaque
# tour relisait 10 000 à 14 000 jetons (60-75 s d'écran figé après chaque outil) alors que 87 à 93 % du prompt était
# inchangé. Un modèle à état récurrent ne peut reculer qu'à un point de reprise, et le défaut les espace de 8 192
# jetons. À 256, chaque requête en pose un en fin de prompt : seul le dernier tour est relu. Coût : l'état récurrent
# (≈ 61 Mio sur le 35B) par point, 32 au plus, en mémoire hôte. Sans effet sur un modèle à attention pure.
ARGUMENTS_POINTS_DE_REPRISE = ("--checkpoint-min-step", "256", "--ctx-checkpoints", "32")


def _motif_experts(blocs: list[int]) -> str:
    """Expression régulière ciblant les tenseurs d'experts des blocs déportés.

    `--n-cpu-moe N` ne conviendrait PAS : il déporte les N PREMIERS blocs, alors que le
    planificateur choisit les plus lourds, où qu'ils soient (mesuré : [4, 35, 36, 37, 38, 39]).
    Traduire son choix en un compte trahirait sa décision. `--override-tensor` cible exactement.
    """
    indices = "|".join(str(bloc) for bloc in sorted(blocs))
    return rf"blk\.({indices})\.ffn_(gate|up|down)_exps\.weight=CPU"


def construire_commande(plan: PlanChargement, binaire: Path) -> list[str]:
    """Traduit le plan en ligne de commande. Aucune valeur n'est choisie ici.

    `--no-webui` : le serveur sert sa propre interface, inutile et exposée pour rien derrière notre
    nginx. `--jinja` : le gabarit du GGUF porte la syntaxe d'appel d'outil que le modèle a apprise ;
    sans lui, llama-server rend un format générique que le modèle n'a jamais vu.
    """
    commande = [
        str(binaire),
        "--model", plan.chemin_modele,
        "--alias", plan.nom_affiche,
        "--host", "127.0.0.1",
        "--port", str(port()),
        "--ctx-size", str(plan.contexte),
        "--batch-size", str(plan.batch),
        "--n-gpu-layers", str(plan.couches_gpu),
        "--jinja",
        "--no-webui",
        # UN seul slot. llama-server en ouvre QUATRE par défaut, et l'état récurrent des blocs
        # hybrides est alloué POUR CHACUN : 242,88 MiB au lieu de 60,72 sur le 35B (mesuré au
        # journal, `CUDA0 RS buffer size`), soit 182 MiB immobilisés pour trois slots que personne
        # n'utilise — le backend est l'unique client de ce serveur, et il sérialise ses requêtes.
        "--parallel", "1",
        *ARGUMENTS_REFLEXION,
        *ARGUMENTS_POINTS_DE_REPRISE,
    ]
    if plan.experts_deportes:
        commande += ["--override-tensor", _motif_experts(plan.experts_deportes)]
    if plan.type_kv_cache:
        commande += ["--cache-type-k", plan.type_kv_cache, "--cache-type-v", plan.type_kv_cache]
    if plan.flash_attention is not None:
        commande += ["--flash-attn", "on" if plan.flash_attention else "off"]
    return commande


def demarrer(commande: list[str], variables_env: dict[str, str], journal: IO[Any]) -> subprocess.Popen[bytes]:
    """Lance le serveur en session détachée, pour que l'arbre entier reste maîtrisable."""
    environnement = {**os.environ, **variables_env}
    options: dict[str, Any] = {}
    if sys.platform != "win32":
        options["start_new_session"] = True
    try:
        return subprocess.Popen(  # noqa: S603 — commande construite depuis le plan, pas d'une saisie
            commande, stdout=journal, stderr=subprocess.STDOUT, env=environnement, **options
        )
    except OSError as exc:
        logger.error("Démarrage de llama-server impossible : {}", exc)
        raise EchecChargement(
            Diagnostic(
                cause=CauseEchec.MOTEUR_ABSENT,
                message=f"llama-server n'a pas pu être lancé : {exc}",
                remediation="Vérifier que le binaire existe dans l'image "
                            f"({CHEMIN_BINAIRE}) et qu'il est exécutable.",
                indices={"commande": commande[:2]},
            )
        ) from exc


async def attendre_sante(
    processus: subprocess.Popen[bytes],
    *,
    annulation: asyncio.Event | None = None,
    tentatives_max: int = TENTATIVES_SONDE_MAX,
    intervalle_s: float = INTERVALLE_SONDE_S,
) -> tuple[bool, str]:
    """Sonde `/health` jusqu'à réponse, mort du processus, annulation ou épuisement.

    Rend (prêt, raison). La raison sépare un moteur mort d'un moteur lent : deux causes qui
    appellent des dégradations différentes, et les confondre ferait réduire le contexte d'un
    modèle dont le seul tort était de charger des experts depuis la RAM.
    """
    cible = f"{url_base()}/health"
    async with httpx.AsyncClient(timeout=DELAI_SONDE_HTTP_S) as client:
        for tentative in range(1, tentatives_max + 1):
            if annulation is not None and annulation.is_set():
                return False, "annulation demandée pendant l'attente de démarrage"
            code = processus.poll()
            if code is not None:
                return False, f"le processus llama-server s'est arrêté (code {code})"
            try:
                reponse = await client.get(cible)
                if reponse.status_code == 200:
                    logger.info("llama-server prêt après {} sondage(s)", tentative)
                    return True, ""
            except httpx.HTTPError:
                pass  # pas encore en écoute : le cas normal des premiers tours
            await asyncio.sleep(intervalle_s)
    return False, f"aucune réponse de /health après {tentatives_max * intervalle_s:.0f} s"


def arreter(processus: subprocess.Popen[bytes] | None, delai_s: float = DELAI_ARRET_DOUX_S) -> None:
    """Arrête l'arbre du serveur : SIGTERM au groupe, puis SIGKILL sur ce qui survit.

    Sur le GROUPE et non sur le seul PID : llama-server ne fait pas de fork aujourd'hui, mais un
    orphelin qui garde la VRAM rendrait le chargement suivant impossible avec un message de mémoire
    insuffisante attribué au nouveau modèle. Jamais de `pkill` par motif — il attraperait les
    serveurs des autres projets de cette machine.
    """
    if processus is None or processus.poll() is not None:
        return
    try:
        parent = psutil.Process(processus.pid)
    except psutil.NoSuchProcess:
        return
    enfants = parent.children(recursive=True)
    if sys.platform != "win32":
        try:
            os.killpg(os.getpgid(processus.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError) as exc:
            logger.debug("Groupe de processus déjà parti : {}", exc)
            parent.terminate()
    else:
        parent.terminate()
    _, survivants = psutil.wait_procs([parent, *enfants], timeout=delai_s)
    for restant in survivants:
        logger.warning("llama-server PID {} ne s'arrête pas : SIGKILL.", restant.pid)
        try:
            restant.kill()
        except psutil.NoSuchProcess:
            pass


__all__ = [
    "CHEMIN_BINAIRE",
    "arreter",
    "attendre_sante",
    "binaire_disponible",
    "construire_commande",
    "demarrer",
    "port",
    "resoudre_binaire",
    "url_base",
]
