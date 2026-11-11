#!/usr/bin/env python3
"""Résumeur de compaction sur l'HÔTE : Claude Haiku 5.5 via le compte Claude Code de cette machine.

Demande de Chris (2026-11-10) : les /compact et compactions automatiques ne passent plus par le modèle local
(7 à 8 min avec le 35B), ni par l'API Anthropic, mais par `claude -p` — le compte Claude Code déjà connecté
ici. Le backend (conteneur) n'a pas ce compte : il poste le matériau à ce relais par host.docker.internal.

POST /resumer et /coder {"systeme", "corps"} -> {"texte"}
(/coder sert l'outil `deleguer_code` : code à l'aveugle) ; jeton exigé (en-tête Authorization: Bearer).
Réglages lus dans le .env du dépôt (jamais sourcé) : RESUMEUR_PORT (37927), RESUMEUR_JETON (obligatoire).
Écoute sur docker0 seulement. Aucun outil, aucun réglage utilisateur ni hook : Claude ne fait que résumer.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
MODELE = "claude-haiku-5-5"
EFFORT = "medium"
DELAI_S = 300
SIMULTANES = threading.BoundedSemaphore(2)
DOSSIER_VIDE = Path(tempfile.gettempdir()) / "echohub-resumeur"


def lire_env(cle: str, defaut: str = "") -> str:
    try:
        for ligne in (RACINE / ".env").read_text().splitlines():
            if ligne.startswith(f"{cle}="):
                return ligne.split("=", 1)[1].strip().strip('"') or defaut
    except OSError as exc:
        print(f"[resumeur] .env illisible : {exc}", flush=True)
    return defaut


def adresse_docker0() -> str:
    try:
        sortie = subprocess.run(["ip", "-4", "-o", "addr", "show", "docker0"], capture_output=True, text=True).stdout
    except OSError as exc:
        print(f"[resumeur] adresse de docker0 introuvable ({exc}) : écoute locale seulement", flush=True)
        return "127.0.0.1"
    return sortie.split()[3].split("/")[0] if sortie.split() else "127.0.0.1"


def resumer(systeme: str, corps: str) -> str:
    DOSSIER_VIDE.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", dir=DOSSIER_VIDE, delete=False) as f:
        f.write(systeme)
    env = {"HOME": os.environ["HOME"], "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    try:
        fini = subprocess.run(
            ["claude", "-p", "--model", MODELE, "--effort", EFFORT, "--system-prompt-file", f.name,
             "--tools", "", "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence",
             "--output-format", "json"],
            input=corps, capture_output=True, text=True, timeout=DELAI_S, cwd=DOSSIER_VIDE, env=env)
    finally:
        os.unlink(f.name)
    try:
        sortie = json.loads(fini.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"sortie illisible (code {fini.returncode}) : {fini.stderr[-300:]}") from exc
    if sortie.get("is_error") or not str(sortie.get("result", "")).strip():
        raise RuntimeError(f"Claude n'a rien rendu : {str(sortie.get('result', ''))[:300]}")
    print(f"[resumeur] résumé en {sortie.get('duration_ms')} ms, {sortie.get('total_cost_usd')} $", flush=True)
    return str(sortie["result"]).strip()


AGENT_OUTILS = "Read,Write,Edit,MultiEdit,Glob,Grep"
AGENT_DELAI_S = 900
FICHIER_MAX = 400_000
# Espaces de travail de Haiku : VIERGES, hors de tout projet. Il n'y voit que ce que le harnais y dépose (la
# tâche et ses propres fichiers) : jamais le dossier du projet, son nom ni son chemin (confidentialité, Chris).
ESPACES = Path(tempfile.gettempdir()) / "echohub-haiku"
AGENT_CONSIGNE = (
    "You are the coding hands of a local lead agent. Work ONLY inside the current folder. Write complete, "
    "working files directly with your tools; keep files small, one responsibility each. You cannot run "
    "anything: re-read your code carefully instead (imports/exports match, no undefined names). When done, "
    "answer in at most 8 lines: files written or changed, how to run the tests, anything left unsure."
)


def _empreintes(dossier: Path) -> dict[str, float]:
    return {str(f.relative_to(dossier)): f.stat().st_mtime for f in dossier.rglob("*")
            if f.is_file() and not any(p.startswith(".") for p in f.relative_to(dossier).parts)}


def espace(identifiant: str) -> Path:
    if not identifiant.isalnum() or len(identifiant) > 64:
        raise RuntimeError(f"espace invalide : {identifiant!r}")
    dossier = ESPACES / identifiant
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def deposer(dossier: Path, fichiers: dict[str, str]) -> None:
    """Remet dans l'espace l'état courant des fichiers que Haiku a produits (l'agent local a pu les retoucher)."""
    for chemin, contenu in fichiers.items():
        cible = (dossier / chemin).resolve()
        if dossier.resolve() not in cible.parents:
            raise RuntimeError(f"chemin hors espace : {chemin!r}")
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(contenu)


def _lancer(dossier: Path, tache: str, session: str | None) -> dict[str, object]:
    commande = ["claude", "-p", "--model", MODELE, "--effort", EFFORT, "--tools", AGENT_OUTILS,
                "--allowedTools", AGENT_OUTILS, "--permission-mode", "acceptEdits", "--setting-sources", "",
                "--strict-mcp-config", "--append-system-prompt", AGENT_CONSIGNE, "--output-format", "json"]
    if session:
        commande += ["--resume", session]
    env = {"HOME": os.environ["HOME"], "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    fini = subprocess.run(commande, input=tache, capture_output=True, text=True, timeout=AGENT_DELAI_S,
                          cwd=dossier, env=env)
    try:
        return dict(json.loads(fini.stdout))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"sortie illisible (code {fini.returncode}) : {fini.stderr[-300:]}") from exc


def agir(demande: dict[str, object]) -> dict[str, object]:
    """Haiku en agent dans un espace vierge ; rend le CONTENU des fichiers écrits, que le harnais pose."""
    dossier = espace(str(demande["espace"]))
    fichiers = demande.get("fichiers") or {}
    deposer(dossier, {str(k): str(v) for k, v in dict(fichiers).items()})
    avant = _empreintes(dossier)
    sortie = _lancer(dossier, str(demande["tache"]), demande.get("session") or None)
    apres = _empreintes(dossier)
    modifies = {f: (dossier / f).read_text(errors="replace") for f, t in sorted(apres.items())
                if avant.get(f) != t and (dossier / f).stat().st_size <= FICHIER_MAX}
    texte = str(sortie.get("result", "")).strip().replace(f"{dossier}/", "").replace(str(dossier), ".")
    print(f"[resumeur] agent {dossier.name} : {sortie.get('duration_ms')} ms, {len(modifies)} fichier(s)", flush=True)
    return {"texte": texte, "session": sortie.get("session_id"), "fichiers": modifies,
            "erreur": bool(sortie.get("is_error")), "duree_ms": sortie.get("duration_ms")}


class Relais(BaseHTTPRequestHandler):
    jeton = ""

    def do_POST(self) -> None:  # noqa: N802 — nom imposé par http.server
        autorise = self.headers.get("Authorization") == f"Bearer {self.jeton}"
        if self.path not in ("/resumer", "/coder", "/agent") or not autorise:
            self._repondre(403, {"erreur": "refusé"})
            return
        try:
            demande = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            if self.path == "/agent":
                self._repondre(200, agir(demande))
                return
            with SIMULTANES:
                texte = resumer(str(demande["systeme"]), str(demande["corps"]))
        except Exception as exc:  # noqa: BLE001 — le backend retombe sur le modèle local
            print(f"[resumeur] échec : {exc}", flush=True)
            self._repondre(502, {"erreur": str(exc)[:500]})
            return
        self._repondre(200, {"texte": texte, "modele": MODELE})

    def _repondre(self, code: int, corps: dict[str, object]) -> None:
        donnees = json.dumps(corps, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(donnees)))
        self.end_headers()
        self.wfile.write(donnees)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        print(f"[resumeur] {self.address_string()} {format % args}", flush=True)


def main() -> None:
    Relais.jeton = lire_env("RESUMEUR_JETON")
    if not Relais.jeton:
        raise SystemExit("[resumeur] RESUMEUR_JETON absent du .env : relais non démarré")
    hote, port = adresse_docker0(), int(lire_env("RESUMEUR_PORT", "37927"))
    print(f"[resumeur] {MODELE} (effort {EFFORT}) sur {hote}:{port}", flush=True)
    ThreadingHTTPServer((hote, port), Relais).serve_forever()


if __name__ == "__main__":
    main()
