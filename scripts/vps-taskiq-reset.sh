#!/usr/bin/env bash
# Full async reset: stop workers, delete RabbitMQ queues, cancel active
# pipeline state in Django, then restart async services.
#
# Usage:
#   ./scripts/vps-taskiq-reset.sh
#   ./scripts/vps-taskiq-reset.sh --yes

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=./vps-taskiq-lib.sh
source ./vps-taskiq-lib.sh

ASSUME_YES=0
if [ "${1:-}" = '--yes' ]; then
  ASSUME_YES=1
fi

echo "=== current async state ==="
taskiq_compose ps "${TASKIQ_ASYNC_SERVICES[@]}" || true
echo
taskiq_print_queue_status || true
echo
taskiq_print_db_status || true

echo
echo "This will:"
echo "  - stop scheduler, worker-api, and worker-render"
echo "  - delete RabbitMQ queues: api, render"
echo "  - cancel active PipelineRun and StageExecution rows"
echo "  - restart async services"
echo
echo "It will NOT touch web, caddy, images, volumes, or .env."

if [ "$ASSUME_YES" -ne 1 ]; then
  read -r -p "Type reset to continue: " confirm
  if [ "$confirm" != 'reset' ]; then
    echo "Aborted."
    exit 1
  fi
fi

taskiq_stop_async

echo
echo "==> Deleting RabbitMQ queues"
taskiq_delete_queues

echo
echo "==> Cancelling active Django pipeline state"
taskiq_cancel_active_state

echo
taskiq_start_async

echo
echo "=== verification ==="
taskiq_print_queue_status || true
echo
taskiq_print_db_status || true

if taskiq_detect_stuck; then
  echo
  echo "taskiq reset: complete (idle)"
  exit 0
fi

echo
echo "taskiq reset: complete, but active work still detected" >&2
exit 1
