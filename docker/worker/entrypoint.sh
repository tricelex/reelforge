#!/usr/bin/env bash
# Worker entrypoint: fix HF cache volume ownership, then drop to web.
set -o errexit
set -o nounset
set -o pipefail

readonly cmd="$*"

HF_ROOT="${HF_HOME:-/var/cache/huggingface}"

if [ "$(id -u)" -eq 0 ]; then
  mkdir -p "${HF_ROOT}/hub"
  # Named Docker volumes are root-owned; the app runs as UID web.
  chown -R web:web "${HF_ROOT}"
  # shellcheck disable=SC2086
  exec gosu web $cmd
fi

# shellcheck disable=SC2086
exec $cmd
