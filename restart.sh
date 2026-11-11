#!/usr/bin/env bash
# EchoHub v2 — redémarrage. Les options sont transmises telles quelles aux deux scripts, pour
# qu'un `./restart.sh --docker` n'arrête pas le natif avant de démarrer le conteneur.
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# L'arrêt ne doit pas empêcher le démarrage : si rien ne tournait, stop.sh sort en erreur sur
# certaines options et c'est sans conséquence ici.
"$RACINE/stop.sh" "$@" || true
"$RACINE/start.sh" "$@"
