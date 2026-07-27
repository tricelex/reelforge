#!/usr/bin/env bash
# Restart only the async TaskIQ path without touching RabbitMQ or DB state.
#
# Usage:
#   ./scripts/vps-taskiq-restart.sh

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=./vps-taskiq-lib.sh
source ./vps-taskiq-lib.sh

taskiq_restart_async
