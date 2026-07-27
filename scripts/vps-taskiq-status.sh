#!/usr/bin/env bash
# Combined async-processing incident report: containers, RabbitMQ queues,
# active Django pipeline state, and recent worker logs.
#
# Usage:
#   ./scripts/vps-taskiq-status.sh
#   ./scripts/vps-taskiq-status.sh --no-logs
#
# Exit code 1 when queues are non-empty or active DB work exists.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=./vps-taskiq-lib.sh
source ./vps-taskiq-lib.sh

SHOW_LOGS=1
if [ "${1:-}" = '--no-logs' ]; then
  SHOW_LOGS=0
fi

echo "=== deployed image tag ==="
echo "IMAGE_TAG=$(vps_deployed_image_tag)"

echo
echo "=== async service containers ==="
taskiq_compose ps "${TASKIQ_ASYNC_SERVICES[@]}" web

echo
echo "=== rabbitmq queues ==="
taskiq_print_queue_status

echo
echo "=== django pipeline state ==="
taskiq_print_db_status

if [ "$SHOW_LOGS" -eq 1 ]; then
  echo
  echo "=== recent worker-api logs ==="
  taskiq_compose logs worker-api --tail=40

  echo
  echo "=== recent worker-render logs ==="
  taskiq_compose logs worker-render --tail=40

  echo
  echo "=== recent scheduler logs ==="
  taskiq_compose logs scheduler --tail=20
fi

echo
if taskiq_detect_stuck; then
  echo "taskiq status: idle"
  exit 0
fi

echo "taskiq status: stuck or active work detected" >&2
exit 1
