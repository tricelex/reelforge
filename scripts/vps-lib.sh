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
: "${VPS_APP_DIR:=/opt/reelforge}"

vps_ssh() {
  ssh -o ConnectTimeout=10 "${VPS_USER}@${VPS_HOST}" "$@"
}

# Runs a remote command with a TTY allocated — needed for interactive
# commands like `python manage.py shell` or `bash`.
vps_ssh_tty() {
  ssh -t -o ConnectTimeout=10 "${VPS_USER}@${VPS_HOST}" "$@"
}

# Read the IMAGE_TAG persisted on the VPS (written by deploy workflow).
# Falls back to the tag on the running web container.
vps_deployed_image_tag() {
  vps_ssh "cd ${VPS_APP_DIR} && \
    if [ -f .env ] && grep -q '^IMAGE_TAG=' .env; then \
      grep -m1 '^IMAGE_TAG=' .env | cut -d= -f2-; \
    else \
      docker compose ps web --format '{{.Image}}' | sed 's/.*://'; \
    fi"
}

# Run docker compose on the VPS with IMAGE_TAG set from the deployed release.
vps_compose() {
  local tag
  tag="$(vps_deployed_image_tag)"
  # shellcheck disable=SC2029
  vps_ssh "cd ${VPS_APP_DIR} && IMAGE_TAG='${tag}' docker compose $(printf '%q ' "$@")"
}
