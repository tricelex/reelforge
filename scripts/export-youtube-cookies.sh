#!/usr/bin/env bash
# Export YouTube cookies from a local browser for yt-dlp on the VPS worker.
#
# Usage:
#   ./scripts/export-youtube-cookies.sh [browser]
#
# Browser defaults to "chrome". Other common values: safari, firefox, brave, edge.
# Output: config/secrets/youtube-cookies.txt (gitignored)
#
# Requires a logged-in YouTube session in the chosen browser.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

BROWSER="${1:-chrome}"
OUT_DIR="config/secrets"
OUT_FILE="${OUT_DIR}/youtube-cookies.txt"
PROBE_URL="https://www.youtube.com/watch?v=jNQXAC9IVRw"

mkdir -p "${OUT_DIR}"
chmod 700 "${OUT_DIR}"

if command -v yt-dlp >/dev/null 2>&1; then
  YTDLP=(yt-dlp)
else
  echo "Installing yt-dlp with pip (user install)..." >&2
  python3 -m pip install --user --quiet yt-dlp
  YTDLP=(python3 -m yt_dlp)
fi

echo "==> Exporting YouTube cookies from ${BROWSER} -> ${OUT_FILE}"
set +e
"${YTDLP[@]}" \
  --cookies-from-browser "${BROWSER}" \
  --cookies "${OUT_FILE}" \
  --skip-download \
  --no-check-certificates \
  --quiet \
  "${PROBE_URL}"
probe_status=$?
set -e

if [ ! -s "${OUT_FILE}" ]; then
  echo "Cookie export failed: ${OUT_FILE} is empty." >&2
  exit 1
fi

if [ "${probe_status}" -ne 0 ]; then
  echo "==> Probe request failed (status ${probe_status}), but cookies were saved." >&2
fi

chmod 600 "${OUT_FILE}"
echo "==> Wrote $(wc -l < "${OUT_FILE}" | tr -d ' ') lines to ${OUT_FILE}"
