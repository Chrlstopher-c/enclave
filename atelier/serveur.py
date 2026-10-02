"""Service d'exécution de l'atelier — reçoit une commande ou du code, l'exécute root, rend le résultat.

C'est le seul processus qui écoute dans le conteneur atelier. Il n'est JAMAIS publié sur l'hôte :
Compose l'expose uniquement sur le réseau interne de la pile, où seul le backend l'atteint. Un jeton
partagé (`ATELIER_JETON`) garde chaque route d'exécution — sans lui, n'importe quel conteneur du
réseau exécuterait du shell root ici. Le repli est FERMÉ : jeton absent de l'environnement =
exécution refusée, jamais ouverte par défaut.

L'agent est root dans ce conteneur, avec réseau et PATH complet, et c'est voulu : l'isolation vient
de la frontière du conteneur (aucun chemin de l'hôte monté, ressources bornées par Compose), pas de
privilèges abaissés. Chaque conversation travaille dans `/workspace/<sous_dossier>`, un volume
partagé avec le backend — un fichier produit ici est balayé et rattaché à la conversation.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Literal

import threading

import apercu
import processus
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

# Racine des espaces de travail, montée sur le volume partagé avec le backend. Chaque conversation a
# son sous-dossier ; l'agent peut se déplacer ailleurs dans le conteneur, mais son point de départ
# est toujours là.
WORKSPACE = Path(os.environ.get("ATELIER_WORKSPACE", "/workspace"))
# Racine des PROJETS : dossier de l'hôte monté ici, où une conversation liée à un projet travaille.
PROJETS = Path(os.environ.get("ATELIER_PROJETS", "/projets"))
# « uid:gid » de l'utilisateur de l'hôte. L'agent est root ici : sans cette rétrocession, tout ce
# qu'il crée sur un dossier de l'hôte appartient à root, et le backend natif comme l'utilisateur ne
# peuvent plus y écrire. Vide = rien n'est rétrocédé (backend lui-même root, en conteneur).
PROPRIETAIRE = os.environ.get("ATELIER_PROPRIETAIRE", "").strip()

Racine = Literal["workspace", "projets"]

# Sortie bornée : une compilation bavarde ou un `apt install` verbeux dépasse vite le raisonnable.
# Le backend retronque pour le modèle ; cette borne-ci protège la mémoire du service.
MAX_SORTIE_OCTETS = 1_000_000

_JETON = os.environ.get("ATELIER_JETON", "")


class RequeteCommande(BaseModel):
    commande: str = Field(min_length=1)
    sous_dossier: str = Field(min_length=1)
    timeout_s: int = Field(gt=0, le=3600)
    racine: Racine = "workspace"


class RequetePython(BaseModel):
    code: str = Field(min_length=1)
    sous_dossier: str = Field(min_length=1)
    timeout_s: int = Field(gt=0, le=3600)
    racine: Racine = "workspace"


class RequeteProcessus(BaseModel):
    sous_dossier: str = Field(min_length=1)
    racine: Racine = "workspace"
    nom: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_.-]*$")
    commande: str = ""
    lignes: int = Field(default=80, gt=0, le=400)


class RequeteApercu(BaseModel):
    port: int = Field(gt=1023, lt=65536)


class Resultat(BaseModel):
    code_retour: int
    sortie: str
    erreur: str
    duree_s: float
    tue: bool


def verifier_jeton(x_atelier_jeton: str = Header(default="")) -> None:
    """Repli fermé : sans jeton configuré, ou jeton faux, l'exécution est refusée."""
    if not _JETON or x_atelier_jeton != _JETON:
        raise HTTPException(status_code=401, detail="Jeton d'atelier absent ou invalide.")


def _dossier_travail(sous_dossier: str, racine: Racine = "workspace") -> Path:
    """Résout `/workspace/<sous_dossier>`, refuse toute sortie de la racine, crée le dossier.

    Le sous-dossier vient du backend (donc de confiance), mais il est validé quand même : un `..`
    ou un chemin absolu ne doit jamais faire écrire hors du volume partagé.
    """
    base = (PROJETS if racine == "projets" else WORKSPACE).resolve()
    cible = (base / sous_dossier).resolve()
    if cible == base or base not in cible.parents:
        raise HTTPException(status_code=400, detail=f"Sous-dossier hors {racine} : « {sous_dossier} ».")
    if racine == "projets" and not cible.is_dir():
        raise HTTPException(status_code=404, detail=f"Projet absent : « {sous_dossier} ».")
    cible.mkdir(parents=True, exist_ok=True)
    return cible


def _retroceder(dossier: Path) -> None:
    """Rend à l'utilisateur de l'hôte ce que root vient de créer dans `dossier`. Jamais fatal.

    `find ! -user` ne touche que ce qui n'est pas déjà à lui : un `node_modules` de 30 000 fichiers
    ne coûte qu'une fois, pas à chaque commande.
    """
    if not PROPRIETAIRE:
        return
    uid = PROPRIETAIRE.split(":")[0]
    try:
        subprocess.run(["find", str(dossier), "!", "-user", uid, "-exec", "chown", "-h", PROPRIETAIRE, "{}", "+"],
                       capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Rétrocession de {} impossible : {}", dossier, exc)


def _tronquer(flux: str | bytes | None) -> str:
    texte = flux.decode("utf-8", "replace") if isinstance(flux, bytes) else (flux or "")
    if len(texte) <= MAX_SORTIE_OCTETS:
        return texte
    return f"{texte[:MAX_SORTIE_OCTETS]}\n[sortie tronquée à {MAX_SORTIE_OCTETS} octets]"


def _lancer(argv: list[str], cwd: Path, timeout_s: int) -> Resultat:
    """Lance `argv` dans `cwd`, borné en temps, et rend le résultat. Ne lève jamais vers l'appelant."""
    debut = time.monotonic()
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        logger.warning("Commande tuée après {} s dans {} : {}", timeout_s, cwd.name, argv[0])
        return Resultat(code_retour=-1, sortie=_tronquer(exc.stdout),
                        erreur=f"{_tronquer(exc.stderr)}\n[Processus tué : délai de {timeout_s}s dépassé]",
                        duree_s=time.monotonic() - debut, tue=True)
    except OSError as exc:
        logger.error("Lancement impossible ({}) : {}", argv[0], exc)
        return Resultat(code_retour=-1, sortie="", erreur=f"Lancement impossible : {exc}",
                        duree_s=time.monotonic() - debut, tue=False)
    return Resultat(code_retour=proc.returncode, sortie=_tronquer(proc.stdout),
                    erreur=_tronquer(proc.stderr), duree_s=time.monotonic() - debut, tue=False)


def _executer_python(code: str, cwd: Path, timeout_s: int) -> Resultat:
    """Écrit le code dans un fichier temporaire HORS workspace et le lance.

    Passer par un fichier évite la limite de taille d'argument d'un `python3 -c`, et le poser hors
    du workspace évite qu'il soit balayé comme un fichier produit par la conversation. Sans `-I` :
    l'atelier a un vrai environnement, un paquet installé par `pip` doit être visible.
    """
    fichier = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
    try:
        fichier.write(code)
        fichier.close()
        return _lancer(["python3", fichier.name], cwd, timeout_s)
    finally:
        Path(fichier.name).unlink(missing_ok=True)


app = FastAPI(title="EchoHub — atelier d'exécution")


@app.get("/sante")
def sante() -> dict[str, str]:
    """Sonde ouverte (pas de jeton) : sert au healthcheck Docker via curl localhost."""
    return {"statut": "ok", "jeton_configure": "oui" if _JETON else "non"}


@app.post("/executer/commande", response_model=Resultat, dependencies=[Depends(verifier_jeton)])
def executer_commande(requete: RequeteCommande) -> Resultat:
    cwd = _dossier_travail(requete.sous_dossier, requete.racine)
    logger.info("commande dans {}:{} (timeout {}s)", requete.racine, requete.sous_dossier, requete.timeout_s)
    resultat = _lancer(["bash", "-lc", requete.commande], cwd, requete.timeout_s)
    _retroceder(cwd)
    return resultat


@app.post("/executer/python", response_model=Resultat, dependencies=[Depends(verifier_jeton)])
def executer_python(requete: RequetePython) -> Resultat:
    cwd = _dossier_travail(requete.sous_dossier, requete.racine)
    logger.info("python dans {}:{} (timeout {}s)", requete.racine, requete.sous_dossier, requete.timeout_s)
    resultat = _executer_python(requete.code, cwd, requete.timeout_s)
    _retroceder(cwd)
    return resultat


@app.post("/processus/{action}", dependencies=[Depends(verifier_jeton)])
def piloter_processus(action: str, requete: RequeteProcessus) -> dict[str, object]:
    """Processus de fond (serveur de dev…) : lancer, journal, arreter, lister."""
    cwd = _dossier_travail(requete.sous_dossier, requete.racine)
    try:
        if action == "lister":
            return {"processus": processus.lister(cwd)}
        if not requete.nom:
            raise HTTPException(status_code=422, detail="Nom de processus requis.")
        if action == "lancer":
            if not requete.commande.strip():
                raise HTTPException(status_code=422, detail="Commande requise.")
            return processus.lancer(cwd, requete.nom, requete.commande)
        if action == "journal":
            return processus.journal(cwd, requete.nom, requete.lignes)
        if action == "arreter":
            resultat = processus.arreter(cwd, requete.nom)
            _retroceder(cwd)
            return resultat
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Aucun processus « {requete.nom} » ici.") from exc
    raise HTTPException(status_code=404, detail=f"Action inconnue : {action}.")


@app.get("/apercu", dependencies=[Depends(verifier_jeton)])
def lire_apercu() -> dict[str, object]:
    """Port pointé par le relais d'aperçu, et ports en écoute qu'il peut servir."""
    return {"port": apercu.port_cible(), "ports": apercu.ports_ecoutes()}


@app.post("/apercu", dependencies=[Depends(verifier_jeton)])
def pointer_apercu(requete: RequeteApercu) -> dict[str, object]:
    try:
        apercu.pointer(requete.port)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return lire_apercu()


# Serveurs MCP montés sur /opt/mcp (dossier de l'hôte, lecture seule), servis en HTTP sur le réseau
# interne par `mcp_http.py`, jeton de l'atelier exigé. Absent = rien à démarrer, pas une erreur.
SERVEURS_MCP = {"pty-mcp": 8932, "log-watcher-mcp": 8933}
_RACINE_MCP = Path("/opt/mcp")
_PYTHON_MCP = "/opt/mcp-venv/bin/python"


def _demarrer_mcp() -> None:
    for nom, port in SERVEURS_MCP.items():
        script = _RACINE_MCP / nom / "mcp_server.py"
        if not script.is_file():
            continue
        try:
            subprocess.Popen([_PYTHON_MCP, str(Path(__file__).with_name("mcp_http.py")), str(script), str(port)],
                             cwd="/projets" if Path("/projets").is_dir() else "/", start_new_session=True)
            logger.info("Serveur MCP {} servi sur le port {}", nom, port)
        except OSError as exc:
            logger.error("Serveur MCP {} non démarré : {}", nom, exc)


def _demarrer_relais() -> None:
    serveur = uvicorn.Server(uvicorn.Config(apercu.app, host="0.0.0.0", port=apercu.PORT_APERCU,
                                            log_level="warning"))
    threading.Thread(target=serveur.run, name="relais-apercu", daemon=True).start()


if __name__ == "__main__":
    if not _JETON:
        logger.warning("ATELIER_JETON absent : toutes les exécutions seront refusées (repli fermé).")
    _demarrer_relais()
    _demarrer_mcp()
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
