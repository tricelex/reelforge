#!/usr/bin/env bash
# One-time, idempotent bootstrap for a fresh Ubuntu/Debian VPS that will run
# ReelForge's web/scheduler/worker/caddy stack. Run once, as root, right
# after first login:
#
#   ./vps-bootstrap.sh "ssh-ed25519 AAAA...your-laptop-pubkey"
#
# What it does:
#   - Creates a non-root `deploy` user (sudo + docker groups) with your
#     pubkey installed, so you have a way in that isn't root.
#   - Generates a SEPARATE ed25519 keypair for GitHub Actions and adds its
#     public half to `deploy`'s authorized_keys. Prints the private half at
#     the end — paste that into the VPS_SSH_PRIVATE_KEY GitHub secret.
#   - Installs Docker Engine + the compose plugin from Docker's official repo.
#   - Configures ufw (22/80/443 only) and fail2ban.
#   - Adds an 8GB swapfile (OOM safety net for the worker's whisperx/torch
#     workload) and sets vm.swappiness=10.
#   - Configures Docker's json-file log driver with rotation, so long-running
#     worker/ffmpeg logs can't fill the disk.
#   - Creates /opt/***REMOVED***, owned by `deploy`, ready for docker-compose.yml
#     + Caddyfile + .env (see docs/deployment/vps-deployment-guide.md).
#
# What it deliberately does NOT do: touch SSH daemon auth settings (no
# disabling root/password login). Do that manually, only after confirming
# `ssh deploy@<vps-ip>` works from your own machine — see the deployment
# guide. Getting that order wrong on a fresh VPS with no console access is
# how you lock yourself out.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo 'Run this as root (or with sudo).' >&2
  exit 1
fi

LAPTOP_PUBKEY="${1:-}"
if [ -z "$LAPTOP_PUBKEY" ]; then
  echo "Usage: $0 \"ssh-ed25519 AAAA...your-laptop-pubkey\"" >&2
  exit 1
fi

DEPLOY_USER='deploy'
APP_DIR='/opt/***REMOVED***'

echo '==> Updating system packages'
apt-get update -y
apt-get upgrade -y

echo '==> Creating deploy user'
if ! id -u "$DEPLOY_USER" >/dev/null 2>&1; then
  adduser --disabled-password --gecos '' "$DEPLOY_USER"
fi
usermod -aG sudo "$DEPLOY_USER"

install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
AUTH_KEYS="/home/$DEPLOY_USER/.ssh/authorized_keys"
touch "$AUTH_KEYS"
grep -qxF "$LAPTOP_PUBKEY" "$AUTH_KEYS" || echo "$LAPTOP_PUBKEY" >> "$AUTH_KEYS"

echo '==> Generating a dedicated GitHub Actions deploy keypair'
GH_KEY="/home/$DEPLOY_USER/.ssh/gh_actions_deploy"
if [ ! -f "$GH_KEY" ]; then
  ssh-keygen -t ed25519 -f "$GH_KEY" -N '' -C 'github-actions-deploy'
fi
grep -qxF "$(cat "${GH_KEY}.pub")" "$AUTH_KEYS" || cat "${GH_KEY}.pub" >> "$AUTH_KEYS"

chmod 600 "$AUTH_KEYS" "$GH_KEY"
chmod 644 "${GH_KEY}.pub"
chown -R "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"

echo '==> Installing Docker Engine'
if ! command -v docker >/dev/null 2>&1; then
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck disable=SC1091
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
usermod -aG docker "$DEPLOY_USER"

echo '==> Configuring Docker log rotation'
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF
systemctl restart docker

echo '==> Configuring firewall (ufw)'
apt-get install -y ufw
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo '==> Configuring fail2ban'
apt-get install -y fail2ban
cat > /etc/fail2ban/jail.d/sshd.local <<'EOF'
[sshd]
enabled = true
maxretry = 5
bantime = 1h
EOF
systemctl enable --now fail2ban
systemctl restart fail2ban

echo '==> Adding an 8GB swapfile (OOM safety net)'
if [ ! -f /swapfile ]; then
  fallocate -l 8G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -qxF '/swapfile none swap sw 0 0' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
cat > /etc/sysctl.d/99-***REMOVED***-swappiness.conf <<'EOF'
vm.swappiness=10
EOF
sysctl --system >/dev/null

echo '==> Scaffolding /opt/***REMOVED***'
mkdir -p "$APP_DIR"
chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"

cat <<EOF

==> Bootstrap complete.

Next steps (see docs/deployment/vps-deployment-guide.md):
  1. From your laptop, confirm you can log in as the deploy user:
       ssh $DEPLOY_USER@<vps-ip>
     Do NOT disable root/password SSH login until this works.

  2. Add these as GitHub Actions secrets on the repo:
       VPS_HOST = <vps-ip>
       VPS_USER = $DEPLOY_USER
       VPS_SSH_PRIVATE_KEY = (contents of $GH_KEY, printed below)

  3. Create $APP_DIR/.env from config/.env.template with real production
     values, then run: docker login ghcr.io (as $DEPLOY_USER, using a
     GitHub PAT with read:packages scope).

----- BEGIN $GH_KEY (copy into VPS_SSH_PRIVATE_KEY) -----
EOF
cat "$GH_KEY"
echo "----- END $GH_KEY -----"
