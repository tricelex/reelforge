#!/usr/bin/env bash
# Tail logs for one service (or all) on the VPS.
#
# Usage:
#   ./scripts/vps-logs.sh                      # follow all services, last 200 lines
#   ./scripts/vps-logs.sh worker                # follow just the worker
#   ./scripts/vps-logs.sh worker --since 1h      # last hour, then follow
#   ./scripts/vps-logs.sh caddy --no-follow --tail=500

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=./vps-lib.sh
source ./vps-lib.sh

SERVICE=''
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then
  SERVICE="$1"
  shift
fi

EXTRA_ARGS="$*"
if [ -z "$EXTRA_ARGS" ]; then
  EXTRA_ARGS='--tail=200 -f'
fi

echo "==> docker compose logs ${EXTRA_ARGS} ${SERVICE} (Ctrl-C to stop)"
vps_ssh_tty "cd ${VPS_APP_DIR} && docker compose logs ${EXTRA_ARGS} ${SERVICE}"
