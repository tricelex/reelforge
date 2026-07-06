#!/usr/bin/env bash
# Downloads the 16 curated fonts. Prefer download_fonts.py (handles variable
# fonts); this wrapper exists for the plan's shell entrypoint.
set -euo pipefail
cd "$(dirname "$0")"
exec python3 download_fonts.py
