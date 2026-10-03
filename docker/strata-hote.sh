#!/usr/bin/env bash
# Serveur Strata sur l'HÔTE, pour le mode Docker d'EchoHub.
#   docker/strata-hote.sh demarrer | arreter | etat
#
# Strata (moteur de Qwen3.8-Flash-Next) est compilé pour l'hôte, pas pour l'image : il tourne ici et
# le backend le pilote par HTTP. Il démarre À VIDE (--lazy) : le modèle n'est chargé que sur
# POST /v1/load, quand le superviseur d'EchoHub l'a décidé — la VRAM reste libre sinon.
# Il n'écoute que sur docker0 (joint du conteneur par host.docker.internal), clé exigée.
#
# Variables lues dans .env (jamais sourcé : `$$` du hash d'auth y deviendrait un PID) :
#   STRATA_DIR     dossier de Strata (vide = Strata non utilisé, rien n'est lancé)
#   STRATA_CONFIG  config écrite par son setup, relative à STRATA_DIR (strata-iq2_xs.json)
#   STRATA_PORT    port d'écoute (37926)
#   STRATA_JETON   clé d'API, obligatoire
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGS="$RACINE/logs"
FICHIER_PID="$LOGS/strata.pid"

lire_env() {
    local valeur
    valeur="$(grep -E "^$1=" "$RACINE/.env" 2>/dev/null | tail -1 | cut -d= -f2-)" || true
    valeur="${valeur%\"}"; valeur="${valeur#\"}"
    printf '%s' "$valeur"
}

journal() { echo "[strata] $*"; }

pid_vivant() {
    [ -f "$FICHIER_PID" ] && kill -0 "$(cat "$FICHIER_PID")" 2>/dev/null
}

demarrer() {
    local dossier config port jeton ip
    dossier="$(lire_env STRATA_DIR)"
    [ -n "$dossier" ] || { journal "STRATA_DIR absent du .env : Strata non démarré"; return 0; }
    config="$(lire_env STRATA_CONFIG)"; config="${config:-strata-iq2_xs.json}"
    port="$(lire_env STRATA_PORT)"; port="${port:-37926}"
    jeton="$(lire_env STRATA_JETON)"
    [ -n "$jeton" ] || { journal "ERREUR : STRATA_JETON vide — Strata n'écoute jamais sans clé"; return 1; }
    [ -x "$dossier/.venv/bin/python" ] || { journal "ERREUR : $dossier/.venv absent (lancer son setup.sh)"; return 1; }
    if pid_vivant; then
        journal "déjà démarré (PID $(cat "$FICHIER_PID"))"
        return 0
    fi
    ip="$(ip -4 -o addr show docker0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)"
    [ -n "$ip" ] || { journal "ERREUR : interface docker0 introuvable"; return 1; }
    mkdir -p "$LOGS"
    # setsid : le moteur est un enfant du serveur, `arreter` les tue ensemble par leur groupe.
    (cd "$dossier" && STRATA_API_KEY="$jeton" setsid nohup "$dossier/.venv/bin/python" "$dossier/serve/server.py" \
        --engine strata --config "$dossier/$config" --host "$ip" --port "$port" --lazy \
        >"$LOGS/strata.log" 2>&1 & echo $! >"$FICHIER_PID")
    journal "démarré à vide sur $ip:$port (PID $(cat "$FICHIER_PID"), journal logs/strata.log)"
}

arreter() {
    if ! pid_vivant; then
        journal "non démarré"
        rm -f "$FICHIER_PID"
        return 0
    fi
    local pid
    pid="$(cat "$FICHIER_PID")"
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid"
    for _ in $(seq 1 30); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
    done
    kill -0 "$pid" 2>/dev/null && kill -KILL -- "-$pid" 2>/dev/null || true
    rm -f "$FICHIER_PID"
    journal "arrêté"
}

etat() {
    if pid_vivant; then
        journal "démarré (PID $(cat "$FICHIER_PID"))"
    else
        journal "non démarré"
    fi
}

case "${1:-}" in
    demarrer) demarrer ;;
    arreter) arreter ;;
    etat) etat ;;
    *) echo "usage : $0 demarrer | arreter | etat" >&2; exit 2 ;;
esac
