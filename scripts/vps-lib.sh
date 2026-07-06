#!/usr/bin/env bash
# Shared config loader for scripts/vps-*.sh. Not meant to be run directly —
# sourced by the other vps-*.sh scripts.

_VPS_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$_VPS_LIB_DIR/vps.env" ]; then
  # shellcheck disable=SC1091
  source "$_VPS_LIB_DIR/vps.env"
fi

: "${VPS_HOST:?Set VPS_HOST in scripts/vps.env (copy from vps.env.example) or export it}"
: "${VPS_USER:?Set VPS_USER in scripts/vps.env (copy from vps.env.example) or export it}"
: "${VPS_APP_DIR:=/opt/***REMOVED***}"

vps_ssh() {
  ssh -o ConnectTimeout=10 "${VPS_USER}@${VPS_HOST}" "$@"
}

# Runs a remote command with a TTY allocated — needed for interactive
# commands like `python manage.py shell` or `bash`.
vps_ssh_tty() {
  ssh -t -o ConnectTimeout=10 "${VPS_USER}@${VPS_HOST}" "$@"
}
