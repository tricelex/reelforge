#!/usr/bin/env bash
# Restart one service (or all) on the VPS without pulling new images or
# re-running migrations — use this for "it's stuck, kick it" situations.
# For an actual redeploy (new code), push to main and let the Deploy
# workflow handle it instead.
#
# Usage:
#   ./scripts/vps-restart.sh            # restart everything
#   ./scripts/vps-restart.sh worker      # restart just the worker

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=./vps-lib.sh
source ./vps-lib.sh

SERVICE="${1:-}"

echo "==> docker compose restart ${SERVICE}"
vps_ssh "cd ${VPS_APP_DIR} && docker compose restart ${SERVICE}"
vps_ssh "cd ${VPS_APP_DIR} && docker compose ps ${SERVICE}"
