# VPS deployment guide

Moves `web`, `worker`, and `scheduler` off Railway and onto a dedicated VPS, fronted by Caddy for
HTTPS on *****REMOVED***.29signals.net**. Postgres, Redis, and RabbitMQ keep running on the existing
Coolify VPS and are reached over the public internet. The frontend stays on Railway, unchanged.

Deploys are fully automated after initial setup: every push to `main` triggers
`.github/workflows/deploy.yml`, which builds images, pushes them to GitHub Container Registry
(GHCR), and SSHes into the VPS to pull and restart. You should never need to log into the VPS again
after the steps below.

**Why this exists:** the worker kept crashing on Railway. `python -m taskiq worker` defaults to
`--workers 2 --max-async-tasks 100` — up to 200 concurrent task slots — and the worker image bundles
`mediapipe`/`scenedetect` plus `ffmpeg` subprocesses. That's an all but guaranteed OOM kill on
a memory-capped plan. `docker-compose.vps.yml` fixes this with explicit concurrency caps
(`--workers 1 --max-async-tasks 2`) and a per-container memory ceiling, so a runaway task kills only
itself and gets restarted automatically instead of taking the whole app down.

---

## 0. Prerequisites checklist

- [ ] VPS purchased (this guide assumes Ubuntu; adjust package manager commands if different).
- [ ] Root access to the VPS (password from your provider's panel/email).
- [ ] Coolify VPS's Postgres/Redis/RabbitMQ connection details (host, port, user, password).
- [ ] Access to the `29signals.net` DNS zone on Namecheap.
- [ ] Admin access to the `tricelex/***REMOVED***` GitHub repo (to add secrets).
- [ ] Cloudflare R2 credentials, `OPENAI_API_KEY`, `PYANNOTEAI_API_KEY` (same ones used today).

---

## 1. First login & user setup

Every command below is labeled with the machine it runs on. You'll have two terminals open at once
partway through — pay attention to which prompt each block is for.

**Do you already have an SSH keypair on your laptop?** Check:

```bash
# on your laptop
cat ~/.ssh/id_ed25519.pub
```

If that file doesn't exist, create one first: `ssh-keygen -t ed25519` (accept the defaults), then
re-run the `cat` command. You'll paste this public key's contents into a command below.

**Step 1 — copy the bootstrap script from your repo checkout to the VPS.** Run this from the
`***REMOVED***` repo directory on your laptop (it will prompt for the VPS root password — the one your
provider emailed/showed you):

```bash
# on your laptop, from the ***REMOVED*** repo directory
scp scripts/vps-bootstrap.sh root@<VPS_IP>:~/
```

**Step 2 — log into the VPS as root** (this opens a shell *on the VPS* — everything after this
until Step 5 runs there):

```bash
# on your laptop
ssh root@<VPS_IP>
```

**Step 3 — run the script**, now that you're inside that root SSH session on the VPS. Pass your
laptop's public key (the one you printed above) as the argument:

```bash
# on the VPS (inside the root SSH session from Step 2)
chmod +x vps-bootstrap.sh
./vps-bootstrap.sh "ssh-ed25519 AAAA...your-laptop-key you@laptop"
```

This creates a `deploy` user (sudo + docker groups) with your pubkey installed, installs Docker
Engine + the compose plugin, configures ufw (22/80/443 only) + fail2ban, adds an 8GB swapfile as an
OOM safety net, configures Docker log rotation, and generates a **separate** ed25519 keypair for
GitHub Actions. It prints that private key at the end — copy it somewhere safe, you'll need it for
the **§2 GitHub Actions secrets** section below.

**Step 4 — verify the new user works, before touching anything else.** Leave the root SSH session
from Step 2 open. Open a **second, new terminal window/tab** on your laptop and run:

```bash
# on your laptop, in a NEW terminal — do not close the root session yet
ssh deploy@<VPS_IP>
```

If this logs you in without a password prompt, it worked. If it fails, **do not proceed** — go back
and fix it using the still-open root session, since that's your only way in at this point.

**Step 5 — only once Step 4 succeeded**, go back to the root SSH session from Step 2 and lock down
SSH so only key-based, non-root login works:

```bash
# on the VPS (back in the root SSH session)
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
# Debian/Ubuntu name the service "ssh", not "sshd" (that name is used on
# RHEL/CentOS-family systems). If this errors with "Unit sshd.service not
# found", use `systemctl restart ssh` instead.
systemctl restart ssh
```

From now on, all access is `ssh deploy@<VPS_IP>` from your laptop — the root session can be closed.

From now on, all access is `ssh deploy@<VPS_IP>` with a key.

---

## 2. GitHub Actions secrets

In the repo: **Settings → Secrets and variables → Actions → New repository secret**.

| Secret | Value |
|---|---|
| `VPS_HOST` | The VPS's IP address |
| `VPS_USER` | `deploy` |
| `VPS_SSH_PRIVATE_KEY` | The private key printed by `vps-bootstrap.sh` (the `gh_actions_deploy` one — **not** your personal key) |

No registry secret is needed — the workflow authenticates to GHCR with the automatic
`GITHUB_TOKEN`.

---

## 3. GHCR pull authentication on the VPS

The container images are **private** (they contain the full app source — `COPY . /code` in both
Dockerfiles — so a public package would leak the private repo). The VPS needs its own one-time login
to pull them; the GitHub Actions deploy job never carries registry credentials itself.

1. Create a GitHub **classic** Personal Access Token with only the `read:packages` scope
   (Settings → Developer settings → Personal access tokens → Tokens (classic)).
2. On the VPS, as `deploy`:

   ```bash
   docker login ghcr.io -u <your-github-username>
   # paste the PAT as the password
   ```

This persists in `~/.docker/config.json` for the `deploy` user, so every future `docker compose
pull` (run automatically by the GitHub Actions job over SSH) just works.

---

## 4. DNS

`29signals.net`'s nameservers point to Netlify, so **Namecheap's Advanced DNS panel won't work** —
Namecheap is just the registrar now; Netlify's DNS panel is the authoritative zone. Add the record
there instead:

Netlify → **Domains** (or the site that manages `29signals.net`) → **DNS panel** for `29signals.net`
→ **Add new record**:

| Type | Name/Host | Value | TTL |
|---|---|---|---|
| A | `***REMOVED***` | `<VPS_IP>` | Netlify default (3600s) |

If you can't find the DNS panel from a site dashboard, go directly to
`app.netlify.com/teams/<your-team>/dns` and select the `29signals.net` zone, or use **Team →
Domains → DNS**. If `29signals.net` isn't showing up as a managed DNS zone in Netlify at all yet
(nameservers pointed there but zone never created), you'll need to add it as a zone first before
you can add records.

Wait for propagation and confirm before the first deploy (Let's Encrypt rate-limits repeated failed
attempts against a domain that doesn't resolve yet):

```bash
dig +short ***REMOVED***.29signals.net
# should print <VPS_IP>
```

---

## 5. The `.env` file

On the VPS: `mkdir -p /opt/***REMOVED***` (already created by the bootstrap script, owned by `deploy`).
Create `/opt/***REMOVED***/.env` — this file **never** comes from git or CI, it's hand-maintained on the
VPS only. Start from `config/.env.template` in this repo and fill in real values:

```bash
nano /opt/***REMOVED***/.env
```

| Variable | Value for this deployment |
|---|---|
| `DOMAIN_NAME` | `***REMOVED***.29signals.net` |
| `DJANGO_SECRET_KEY` | Generate fresh: `python3 -c 'from django.utils.crypto import get_random_string; print(get_random_string(50))'` |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | From the Coolify VPS's Postgres service |
| `DJANGO_DATABASE_HOST` / `DJANGO_DATABASE_PORT` | The Coolify VPS's public Postgres host/port |
| `DJANGO_DATABASE_SSLMODE` | Optional — leave unset (defaults to `prefer`, same as today's behavior) to deploy now. Only set to `require` **after** confirming Postgres on the Coolify VPS has SSL enabled — `require` hard-fails the connection if the server doesn't offer TLS at all, it won't fall back to plaintext |
| `TLS_EMAIL` | Your email, for Let's Encrypt expiry notices |
| `REDIS_URL` | `redis://<user>:<password>@<coolify-host>:<port>` (or `rediss://` if Coolify exposes TLS) — taskiq's result backend |
| `REDIS_CACHE_URL` | Same Redis, different logical DB index (e.g. `.../1` vs `REDIS_URL`'s `.../0`) — **not derived from `REDIS_URL`**, must be set explicitly or Django's cache (and django-axes login tracking) silently falls back to `redis://localhost:6379/1`, which doesn't exist in this topology |
| `RABBITMQ_URL` | `amqp://<user>:<password>@<coolify-host>:<port>/` (or `amqps://` if available) |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_STORAGE_BUCKET_NAME` / `AWS_S3_ENDPOINT_URL` / `AWS_S3_PUBLIC_ENDPOINT_URL` / `AWS_S3_CUSTOM_DOMAIN` | Same Cloudflare R2 credentials already used today |
| `OPENAI_API_KEY` / `PYANNOTEAI_API_KEY` / `ELEVENLABS_API_KEY` | Same as today |
| `SENTRY_DSN`, `LOGFIRE_TOKEN` | Optional, same as today |
| `TASKIQ_WORKERS`, `TASKIQ_MAX_ASYNC_TASKS` | Optional — only set if you want to override the conservative defaults (1 worker process / 2 concurrent tasks) baked into `docker-compose.vps.yml` |

Restrict permissions: `chmod 600 /opt/***REMOVED***/.env`.

---

## 6. Harden the Coolify side (recommended)

Postgres/Redis/RabbitMQ are reachable from the public internet with credentials. Two cheap
hardening steps, in order of value:

1. **Firewall by source IP.** On the Coolify VPS, restrict those ports to the app VPS's IP only:
   ```bash
   ufw allow from <APP_VPS_IP> to any port 5432 proto tcp   # Postgres
   ufw allow from <APP_VPS_IP> to any port 6379 proto tcp   # Redis
   ufw allow from <APP_VPS_IP> to any port 5672 proto tcp   # RabbitMQ
   ```
   Do this in addition to (not instead of) the existing password auth.
2. **Prefer TLS connection strings** if Coolify exposes them (`rediss://`, `amqps://`, and Postgres
   `sslmode=require`, already configured above). If Coolify's Postgres only offers a self-signed
   cert, `sslmode=require` (rather than `verify-full`) still encrypts the connection without needing
   a trusted CA.

---

## 7. First deploy

Push to `main` (or merge a PR into it). Watch **Actions** tab in GitHub for the `Deploy` workflow.
It will:
1. Build `***REMOVED***-web` and `***REMOVED***-worker` images, push to `ghcr.io/tricelex/`.
2. SCP `docker-compose.vps.yml` → `/opt/***REMOVED***/docker-compose.yml` and
   `docker/caddy/Caddyfile.vps` → `/opt/***REMOVED***/Caddyfile`.
3. SSH in, `docker compose pull`, run migrations/collectstatic/compilemessages once, then
   `docker compose up -d`.
4. Curl `https://***REMOVED***.29signals.net/health/?format=json` and fail the job if it's not 200.

If step 4 fails on the very first run, it's most likely DNS/ACME timing — give it a minute and
re-run the job from the Actions tab, or check `docker compose logs caddy` on the VPS.

---

## 8. Post-deploy verification

```bash
ssh deploy@<VPS_IP>
cd /opt/***REMOVED***
docker compose ps                     # all four services should be Up
curl -I https://***REMOVED***.29signals.net/health/?format=json   # 200

# End-to-end web -> RabbitMQ -> worker -> Redis round-trip:
docker compose exec -T web python manage.py trigger_test_task
docker compose logs worker --tail=50 | grep add_task_executed
# expect: add_task_executed result=8
```

---

## 9. Rollback

Images are tagged with both `:latest` and the commit SHA. To roll back to a previous build:

```bash
ssh deploy@<VPS_IP>
cd /opt/***REMOVED***
IMAGE_TAG=<previous-git-sha> docker compose pull
IMAGE_TAG=<previous-git-sha> docker compose up -d
```

Find the previous SHA from the GitHub Actions run history or `git log --oneline`.

---

## 10. Frontend follow-up (outside this repo)

Update the Next.js frontend's API base URL environment variable on Railway to
`https://***REMOVED***.29signals.net` and redeploy the frontend service.

---

## Reference: files involved

| File | Purpose |
|---|---|
| `docker-compose.vps.yml` | Production compose file (deployed as `/opt/***REMOVED***/docker-compose.yml`) |
| `docker/caddy/Caddyfile.vps` | Reverse proxy + TLS config (deployed as `/opt/***REMOVED***/Caddyfile`) |
| `.github/workflows/deploy.yml` | Build, push, and deploy on every push to `main` |
| `scripts/vps-bootstrap.sh` | One-time VPS setup (run manually, once) |
| `config/.env.template` | Source of truth for which env vars `/opt/***REMOVED***/.env` needs |
| `server/apps/main/management/commands/trigger_test_task.py` | Worker connectivity smoke test |

For day-2 operations (logs, one-off commands, restarting a stuck service, diagnosing common
failures) see [vps-operations-guide.md](./vps-operations-guide.md).
