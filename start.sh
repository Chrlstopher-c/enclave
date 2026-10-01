#!/usr/bin/env bash
# EchoHub v2 — démarrage.
#
#   ./start.sh            mode natif : uvicorn + serveur Vite, rechargement à chaud
#   ./start.sh --docker   mode conteneur : image GPU complète (docker compose)
#
# Le mode natif ne compile pas llama-cpp-python pour CUDA : c'est le rôle de l'image Docker.
# Il sert au développement de l'interface et de la logique, pas à mesurer le GPU.
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGS="$RACINE/logs"
MODE="natif"

journal() { echo "[start] $*"; }
echec()   { echo "[start] ERREUR : $*" >&2; exit 1; }

charger_env() {
    [ -f "$RACINE/.env" ] || return 0
    set -a
    # shellcheck disable=SC1091
    . "$RACINE/.env"
    set +a
    journal ".env chargé"
}

# Les journaux sont remis à zéro à chaque démarrage : un fichier de log qui s'accumule sur
# plusieurs sessions ne permet plus de dire quelle exécution a produit quelle erreur.
reinitialiser_logs() {
    mkdir -p "$LOGS"
    : > "$LOGS/backend.log"
    : > "$LOGS/frontend.log"
    : > "$LOGS/atelier.log"
    journal "journaux remis à zéro dans $LOGS"
}

# Un PID encore vivant signifie une instance déjà lancée : démarrer par-dessus donnerait deux
# processus sur le même port et un fichier de PID mensonger.
verifier_libre() {
    local fichier="$LOGS/$1.pid"
    [ -f "$fichier" ] || return 0
    local pid
    pid="$(cat "$fichier")"
    if kill -0 "$pid" 2>/dev/null; then
        echec "$1 tourne déjà (PID $pid) — lancer ./stop.sh d'abord"
    fi
    rm -f "$fichier"
}

# Le venv est en layout POSIX ou Windows selon la machine : on ne devine pas, on regarde.
python_venv() {
    if [ -x "$RACINE/backend/.venv/bin/python" ]; then
        echo "$RACINE/backend/.venv/bin/python"
    elif [ -x "$RACINE/backend/.venv/Scripts/python.exe" ]; then
        echo "$RACINE/backend/.venv/Scripts/python.exe"
    fi
}

preparer_backend() {
    if [ -z "$(python_venv)" ]; then
        journal "création du venv backend"
        python3 -m venv "$RACINE/backend/.venv" || echec "création du venv impossible"
    fi
    local py
    py="$(python_venv)"
    [ -n "$py" ] || echec "interpréteur du venv introuvable après création"
    "$py" -m pip install --quiet --upgrade pip \
        || echec "mise à jour de pip impossible"
    "$py" -m pip install --quiet -r "$RACINE/backend/requirements.txt" \
        || echec "installation des dépendances backend impossible"
    journal "dépendances backend à jour"
}

preparer_frontend() {
    command -v bun >/dev/null 2>&1 || echec "bun introuvable — https://bun.sh"
    [ -d "$RACINE/frontend/node_modules" ] && return 0
    journal "installation des dépendances frontend"
    (cd "$RACINE/frontend" && bun install) || echec "bun install a échoué"
}

# Attente bornée : 60 tentatives d'une seconde. Sans borne, un backend qui ne démarre jamais
# ferait tourner ce script indéfiniment sans rien dire.
attendre_api() {
    local port="$1" i
    for i in $(seq 1 60); do
        if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
            journal "API disponible sur 127.0.0.1:$port (après ${i}s)"
            return 0
        fi
        sleep 1
    done
    journal "AVERTISSEMENT : API muette après 60s — voir $LOGS/backend.log"
}

# Mode natif : les commandes du modèle s'exécutent quand même dans le conteneur atelier, publié sur
# 127.0.0.1. Sans lui, les outils d'exécution rendent un repli « atelier indisponible ». Non fatal :
# l'application reste utilisable sans exécution.
demarrer_atelier() {
    case "${ATELIER_URL:-}" in
        http://127.0.0.1:*|http://localhost:*) ;;
        *) return 0 ;;
    esac
    if ! command -v docker >/dev/null 2>&1; then
        journal "AVERTISSEMENT : docker absent — atelier d'exécution non démarré"
        return 0
    fi
    [ -z "${ECHOHUB_PROJETS_HOTE:-}" ] || mkdir -p "$ECHOHUB_PROJETS_HOTE"
    [ -z "${ECHOHUB_ATELIERS_HOTE:-}" ] || mkdir -p "$ECHOHUB_ATELIERS_HOTE"
    if (cd "$RACINE" && docker compose up -d --build echohub-atelier >>"$LOGS/atelier.log" 2>&1); then
        journal "atelier d'exécution démarré ($ATELIER_URL)"
    else
        journal "AVERTISSEMENT : atelier non démarré — voir $LOGS/atelier.log"
    fi
}

demarrer_natif() {
    # Distincts des défauts v1 (37821/37822) : les deux versions peuvent tourner en même temps
    # sur le même hôte sans se disputer un port (mesuré : bind KO côté v2, servi par la v1).
    local port_api="${ECHOHUB_PORT_API:-37921}" port_front="${ECHOHUB_PORT_FRONT_DEV:-37922}"
    verifier_libre backend
    verifier_libre frontend
    preparer_backend
    preparer_frontend

    local py
    py="$(python_venv)"
    journal "backend sur 127.0.0.1:$port_api"
    # `set -m` (job control) fait de chaque commande lancée en arrière-plan le MENEUR de son
    # propre groupe de processus — $! capture alors ce meneur, PGID compris, et stop.sh peut
    # cibler le groupe entier (kill sur -PID). Testé et écarté : `setsid CMD &` sans job control
    # ne suffit pas — util-linux fait forker setsid(1) en interne quand l'appelant est déjà
    # meneur de groupe, et $! capture alors le PARENT de ce fork (qui attend l'enfant), jamais
    # le vrai meneur du nouveau groupe ; le `kill -PID` qui suit ne trouve personne à tuer, et
    # le reloader continue d'écouter. Sans job control : $! ne désigne que le reloader d'uvicorn ;
    # son worker enfant (--reload en lance un second) survit à un arrêt normal, port toujours en
    # écoute — mesuré.
    (set -m; cd "$RACINE" && PYTHONPATH="$RACINE" "$py" -m uvicorn backend.main:app \
        --host 127.0.0.1 --port "$port_api" --reload \
        --reload-dir backend --reload-exclude '*/tests/*' >>"$LOGS/backend.log" 2>&1 &
        echo $! > "$LOGS/backend.pid")

    journal "frontend sur 127.0.0.1:$port_front"
    # Même raison côté frontend : `bun run dev` spawn node/vite/esbuild comme processus enfants,
    # que $! seul ne capture jamais sans job control.
    (set -m; cd "$RACINE/frontend" && bun run dev --port "$port_front" >>"$LOGS/frontend.log" 2>&1 &
        echo $! > "$LOGS/frontend.pid")

    attendre_api "$port_api"
    journal "interface : http://127.0.0.1:$port_front"
}

demarrer_docker() {
    command -v docker >/dev/null 2>&1 || echec "docker introuvable"
    mkdir -p "$LOGS"
    # Le major de nvidia-uvm change d'un boot à l'autre et le spec CDI le fige : sans cette
    # garde, CUDA meurt dans le conteneur après un reboot (docker/cdi/README.md).
    local recreer=""
    if [ -x /usr/local/sbin/echohub-cdi-regenerer ]; then
        sudo /usr/local/sbin/echohub-cdi-regenerer && true
        case $? in
            0) ;;
            3) recreer="--force-recreate" ;;
            *) echec "régénération du spec CDI impossible" ;;
        esac
    else
        journal "AVERTISSEMENT : echohub-cdi-regenerer absent — voir docker/cdi/README.md"
    fi
    journal "construction et démarrage du conteneur (première fois : compilation CUDA, longue)"
    (cd "$RACINE" && docker compose up -d --build $recreer) || echec "docker compose up a échoué"
    journal "interface : http://127.0.0.1:${ECHOHUB_PORT_WEB:-37820}"
    journal "journaux : docker compose logs -f echohub"
}

case "${1:-}" in
    --docker) MODE="docker" ;;
    --help|-h) sed -n '2,8p' "$0"; exit 0 ;;
    "") ;;
    *) echec "option inconnue : $1" ;;
esac

charger_env
if [ "$MODE" = "docker" ]; then
    demarrer_docker
else
    reinitialiser_logs
    demarrer_natif
fi
