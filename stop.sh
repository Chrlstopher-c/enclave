#!/usr/bin/env bash
# EchoHub v2 — arrêt.
#
#   ./stop.sh            arrête les processus natifs lancés par ./start.sh
#   ./stop.sh --docker   arrête le conteneur (docker compose down)
#
# L'arrêt se fait par PID relevé dans logs/*.pid, jamais par motif de commande : un
# `pkill -f uvicorn` tuerait n'importe quel autre projet Python de la machine.
#
# Le PID enregistré est le meneur d'un groupe de processus (job control `set -m` dans start.sh),
# pas un PID isolé : `kill` cible le groupe entier (-PID), jamais le seul meneur. Mesuré sans
# ça : le reloader enfant d'uvicorn (--reload) et les processus node/esbuild spawnés par
# `bun run dev` survivaient à un `./stop.sh` terminé sans erreur, ports toujours en écoute.
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGS="$RACINE/logs"

journal() { echo "[stop] $*"; }

# Le groupe existe encore si au moins un de ses processus tourne — c'est lui qu'il faut
# interroger, pas le seul PID meneur, qui peut être mort pendant qu'un enfant reste vivant.
groupe_vivant() { pgrep -g "$1" >/dev/null 2>&1; }

# SIGTERM d'abord, puis attente bornée à 20 tentatives d'une demi-seconde, puis SIGKILL. Sans
# borne, un processus qui ignore SIGTERM bloquerait l'arrêt pour toujours.
arreter() {
    local nom="$1" fichier="$LOGS/$1.pid" pid i
    if [ ! -f "$fichier" ]; then
        journal "$nom : aucun PID enregistré"
        return 0
    fi
    pid="$(cat "$fichier")"
    if ! kill -0 "$pid" 2>/dev/null && ! groupe_vivant "$pid"; then
        journal "$nom : PID $pid déjà éteint"
        rm -f "$fichier"
        return 0
    fi
    kill -TERM -- "-$pid" 2>/dev/null || true
    for i in $(seq 1 20); do
        groupe_vivant "$pid" || break
        sleep 0.5
    done
    if groupe_vivant "$pid"; then
        journal "$nom : SIGTERM ignoré après 10s, SIGKILL sur le groupe -$pid"
        kill -KILL -- "-$pid" 2>/dev/null || true
    fi
    rm -f "$fichier"
    journal "$nom arrêté (groupe -$pid)"
}

arreter_docker() {
    command -v docker >/dev/null 2>&1 || { journal "docker introuvable"; return 0; }
    # `down` sans -v : les volumes nommés contiennent les modèles téléchargés et les données
    # utilisateur. Les supprimer se fait à la main, jamais dans un script d'arrêt.
    (cd "$RACINE" && docker compose down) || journal "docker compose down a échoué"
    "$RACINE/docker/strata-hote.sh" arreter || journal "arrêt de Strata en échec"
}

case "${1:-}" in
    --docker) arreter_docker ;;
    --help|-h) sed -n '2,8p' "$0" ;;
    "") arreter frontend; arreter backend ;;
    *) echo "[stop] ERREUR : option inconnue : $1" >&2; exit 1 ;;
esac
