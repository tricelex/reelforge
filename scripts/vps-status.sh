#!/usr/bin/env bash
# Quick health snapshot of the VPS: container states, resource usage, disk,
# swap, and the public health endpoint.
#
# Usage: ./scripts/vps-status.sh

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=./vps-lib.sh
source ./vps-lib.sh

echo "=== docker compose ps ==="
vps_ssh "cd ${VPS_APP_DIR} && docker compose ps"

echo
echo "=== docker stats (one-shot) ==="
vps_ssh "docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}'"

echo
echo "=== disk usage ==="
vps_ssh "df -h / && echo && docker system df"

echo
echo "=== memory & swap ==="
vps_ssh "free -h"

echo
echo "=== public health endpoint ==="
if command -v curl >/dev/null 2>&1; then
  DOMAIN="$(vps_ssh "grep -m1 '^DOMAIN_NAME=' ${VPS_APP_DIR}/.env | cut -d= -f2-" || true)"
  if [ -n "${DOMAIN:-}" ]; then
    curl -fsS -o /dev/null -w 'HTTP %{http_code} in %{time_total}s\n' \
      "https://${DOMAIN}/health/?format=json" || echo 'health check FAILED'
  fi
fi
