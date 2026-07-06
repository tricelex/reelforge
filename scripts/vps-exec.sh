#!/usr/bin/env bash
# Run a one-off command inside a running service container on the VPS.
#
# Usage:
#   ./scripts/vps-exec.sh web python manage.py shell
#   ./scripts/vps-exec.sh web python manage.py trigger_test_task
#   ./scripts/vps-exec.sh web bash
#   ./scripts/vps-exec.sh worker bash
#
# Runs with a TTY (`docker compose exec`, not `exec -T`) so interactive
# commands like `shell` or `bash` work as expected.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=./vps-lib.sh
source ./vps-lib.sh

if [ $# -lt 2 ]; then
  echo "Usage: $0 <service> <command...>" >&2
  echo "  e.g. $0 web python manage.py shell" >&2
  exit 1
fi

SERVICE="$1"
shift

echo "==> docker compose exec ${SERVICE} $*"
vps_ssh_tty "cd ${VPS_APP_DIR} && docker compose exec ${SERVICE} $*"
