#!/usr/bin/env bash
# Upload YouTube cookies to the VPS and configure the worker to use them.
#
# Usage:
#   ./scripts/vps-setup-youtube.sh
#
# Prerequisites:
#   - scripts/vps.env configured (VPS_HOST, VPS_USER, VPS_APP_DIR)
#   - config/secrets/youtube-cookies.txt (run export-youtube-cookies.sh first)
#   - Optional: YOUTUBE_DATA_API_KEY in config/.env for metadata probing fallback

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=./vps-lib.sh
source ./vps-lib.sh

COOKIE_SRC="../config/secrets/youtube-cookies.txt"
REMOTE_SECRETS_DIR="${VPS_APP_DIR}/secrets"
REMOTE_COOKIE_FILE="${REMOTE_SECRETS_DIR}/youtube-cookies.txt"
CONTAINER_COOKIE_PATH="/run/secrets/youtube-cookies.txt"

if [ ! -s "${COOKIE_SRC}" ]; then
  echo "Missing ${COOKIE_SRC}. Run ./scripts/export-youtube-cookies.sh first." >&2
  exit 1
fi

LOCAL_ENV="../config/.env"
API_KEY_VALUE=""
if [ -f "${LOCAL_ENV}" ]; then
  API_KEY_VALUE="$(grep -E '^YOUTUBE_DATA_API_KEY=' "${LOCAL_ENV}" | head -1 | cut -d= -f2- || true)"
fi

echo "==> Creating secrets directory on VPS"
vps_ssh "mkdir -p '${REMOTE_SECRETS_DIR}' && chmod 700 '${REMOTE_SECRETS_DIR}'"

echo "==> Uploading cookies"
scp "${COOKIE_SRC}" "${VPS_USER}@${VPS_HOST}:${REMOTE_COOKIE_FILE}"
vps_ssh "chmod 600 '${REMOTE_COOKIE_FILE}'"

echo "==> Updating ${VPS_APP_DIR}/.env"
vps_ssh "bash -s" <<EOF
set -euo pipefail
ENV_FILE='${VPS_APP_DIR}/.env'
touch "\${ENV_FILE}"
chmod 600 "\${ENV_FILE}"

upsert_env() {
  local key="\$1"
  local value="\$2"
  if grep -q "^\${key}=" "\${ENV_FILE}"; then
    sed -i "s|^\${key}=.*|\${key}=\${value}|" "\${ENV_FILE}"
  else
    printf '%s=%s\n' "\${key}" "\${value}" >> "\${ENV_FILE}"
  fi
}

upsert_env YTDLP_COOKIE_FILE '${CONTAINER_COOKIE_PATH}'
EOF

if [ -n "${API_KEY_VALUE}" ]; then
  echo "==> Setting YOUTUBE_DATA_API_KEY from local config/.env"
  vps_ssh "bash -s" <<EOF
set -euo pipefail
ENV_FILE='${VPS_APP_DIR}/.env'
if grep -q '^YOUTUBE_DATA_API_KEY=' "\${ENV_FILE}"; then
  sed -i 's|^YOUTUBE_DATA_API_KEY=.*|YOUTUBE_DATA_API_KEY=${API_KEY_VALUE}|' "\${ENV_FILE}"
else
  printf 'YOUTUBE_DATA_API_KEY=%s\n' '${API_KEY_VALUE}' >> "\${ENV_FILE}"
fi
EOF
else
  echo "==> No YOUTUBE_DATA_API_KEY in config/.env — skipping API key sync"
  echo "    Metadata probing will rely on yt-dlp cookies only."
fi

echo "==> Syncing docker-compose.yml (cookie volume mount)"
scp ../docker-compose.vps.yml "${VPS_USER}@${VPS_HOST}:${VPS_APP_DIR}/docker-compose.yml"

echo "==> Restarting worker"
vps_ssh "cd '${VPS_APP_DIR}' && docker compose up -d worker"

echo "==> Verifying cookie file inside worker"
vps_ssh "cd '${VPS_APP_DIR}' && docker compose exec -T worker test -f '${CONTAINER_COOKIE_PATH}'"

echo "==> Done. Retry the failed clip source probe task."
