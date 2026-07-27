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
FOLLOW=1
EXTRA_ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --no-follow)
      FOLLOW=0
      shift
      ;;
    *)
      if [ -z "$SERVICE" ] && [[ "$1" != -* ]]; then
        SERVICE="$1"
        shift
      else
        EXTRA_ARGS+=("$1")
        shift
      fi
      ;;
  esac
done

if [ "${#EXTRA_ARGS[@]}" -eq 0 ]; then
  EXTRA_ARGS=(--tail=200)
fi
if [ "$FOLLOW" -eq 1 ]; then
  EXTRA_ARGS+=(-f)
fi

echo "==> docker compose logs ${EXTRA_ARGS[*]} ${SERVICE} (Ctrl-C to stop)"
vps_ssh_tty "cd ${VPS_APP_DIR} && docker compose logs ${EXTRA_ARGS[*]} ${SERVICE}"
