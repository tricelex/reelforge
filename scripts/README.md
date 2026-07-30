# scripts/

Operational scripts for provisioning, deploying to, and debugging the VPS
(`docker-compose.vps.yml`), plus a couple of local dev helpers. Almost
everything here talks to the VPS over SSH — set that up once, then every
`vps-*.sh` script just works.

## One-time setup

1. Your personal SSH public key must already be in the `deploy` user's
   `authorized_keys` on the VPS. If the VPS doesn't exist yet, see
   [`vps-bootstrap.sh`](#vps-bootstrapsh) below and
   `docs/deployment/vps-deployment-guide.md`.
2. Copy the connection template and fill in your VPS's real details:

   ```bash
   cp scripts/vps.env.example scripts/vps.env
   ```

   ```ini
   VPS_HOST=<vps-ip-or-hostname>
   VPS_USER=deploy
   VPS_APP_DIR=/opt/reelforge
   ```

   `scripts/vps.env` is gitignored (matches the `*.env` pattern) — **never
   commit it**, it's per-machine and points at real infrastructure.
3. Confirm you can connect:

   ```bash
   ssh deploy@<vps-ip>
   ```

Every `vps-*.sh` script (except `vps-bootstrap.sh`, which runs as root
*on* the VPS before a `deploy` user even exists) sources
[`vps-lib.sh`](#vps-libsh--vps-taskiq-libsh-shared-helpers-not-run-directly)
to pick up `VPS_HOST` / `VPS_USER` / `VPS_APP_DIR` from `vps.env`
automatically. You never need to pass connection details to individual
scripts.

All scripts are run from the repo root or from inside `scripts/` — both
work, since each script `cd`s to its own directory first. Examples below use
`./scripts/<name>.sh` (repo root).

---

## Quick reference

| Script | What it's for |
|---|---|
| [`vps-bootstrap.sh`](#vps-bootstrapsh) | One-time setup of a fresh VPS (users, Docker, firewall, swap) |
| [`vps-status.sh`](#vps-statussh) | Whole-stack health snapshot (containers, CPU/mem, disk, health endpoint) |
| [`vps-render-status.sh`](#vps-render-statussh) | Is the render worker's current ffmpeg job stuck or just slow? |
| [`vps-taskiq-status.sh`](#vps-taskiq-statussh) | Incident report for the async (TaskIQ/RabbitMQ) pipeline |
| [`vps-taskiq-restart.sh`](#vps-taskiq-restartsh) | Soft restart of scheduler/worker-api/worker-render |
| [`vps-taskiq-reset.sh`](#vps-taskiq-resetsh) | Hard reset: wipe queues + cancel active pipeline runs |
| [`vps-restart.sh`](#vps-restartsh) | Restart one or all `docker compose` services (no image pull) |
| [`vps-logs.sh`](#vps-logssh) | Tail logs for one or all services |
| [`vps-exec.sh`](#vps-execsh) | Run an arbitrary command inside a service container |
| [`vps-setup-youtube.sh`](#vps-setup-youtubesh) | Upload YouTube cookies + configure the worker to use them |
| [`export-youtube-cookies.sh`](#export-youtube-cookiessh) | Export YouTube cookies from your local browser (run before the above) |
| [`create_dev_database.sql`](#create_dev_databasesql) | SQL to bootstrap the local Postgres dev database |
| [`vps-lib.sh`](#vps-libsh--vps-taskiq-libsh-shared-helpers-not-run-directly) / `vps-taskiq-lib.sh` | Shared helpers — not run directly |

---

## `vps-bootstrap.sh`

One-time, idempotent bootstrap for a **fresh** Ubuntu/Debian VPS that will
run the ReelForge web/scheduler/worker/caddy stack. Run once, **as root**,
immediately after first login — before `scripts/vps.env` even exists,
since this is what creates the `deploy` user everything else connects as.

```bash
ssh root@<fresh-vps-ip>
# on the VPS:
./vps-bootstrap.sh "ssh-ed25519 AAAA...your-laptop-pubkey"
```

What it does:
- Creates a non-root `deploy` user (`sudo` + `docker` groups) with your
  pubkey installed — your way in once root/password login gets locked down.
- Generates a **separate** ed25519 keypair for GitHub Actions and adds its
  public half to `deploy`'s `authorized_keys`. Prints the private half at
  the end — that's what goes in the `VPS_SSH_PRIVATE_KEY` GitHub secret.
- Installs Docker Engine + the compose plugin from Docker's official repo.
- Configures `ufw` (22/80/443 only) and `fail2ban`.
- Adds an 8GB swapfile (OOM safety net for ffmpeg/whisperx/torch workloads
  on the render worker) and sets `vm.swappiness=10`.
- Configures Docker's `json-file` log driver with rotation (10MB × 3 files)
  so long-running worker/ffmpeg logs can't fill the disk.
- Creates `/opt/reelforge`, owned by `deploy`, ready for
  `docker-compose.yml` + `Caddyfile` + `.env`.

What it deliberately does **not** do: touch SSH daemon auth settings (no
disabling root/password login). Do that manually, only *after* confirming
`ssh deploy@<vps-ip>` works from your own machine. Getting that order wrong
on a VPS with no console access is how you lock yourself out permanently.

Full walkthrough (GitHub secrets, `.env`, first deploy):
`docs/deployment/vps-deployment-guide.md`.

---

## `vps-status.sh`

Whole-stack health snapshot. Read-only, safe to run anytime.

```bash
./scripts/vps-status.sh
```

Prints, in order:
1. `docker compose ps` — every service's state.
2. `docker stats --no-stream` — one-shot CPU%/mem for every container.
3. `df -h /` and `docker system df` — disk usage.
4. `free -h` — memory & swap.
5. A `curl` against the public `/health/?format=json` endpoint (reads the
   domain from `DOMAIN_NAME` in the VPS's `.env`), reporting HTTP status
   and response time.

Use this first for "is anything on fire" checks. For the async pipeline
specifically (queues, stuck runs), use `vps-taskiq-status.sh` instead. For
"is a specific long-running render actually progressing", use
`vps-render-status.sh`.

---

## `vps-render-status.sh`

Answers "is the render worker stuck, or just mid-ffmpeg-encode?" — built
for checking on long ffmpeg-heavy stages (`assembly`, `clip_render`, etc.)
without SSHing in and hand-assembling `docker top`/`docker stats`/log
commands every time. Read-only.

```bash
./scripts/vps-render-status.sh                  # last 200 log lines
./scripts/vps-render-status.sh --log-lines 500   # more log context
./scripts/vps-render-status.sh --since 30m       # logs from the last 30m instead of a line count
./scripts/vps-render-status.sh --raw-logs        # also dump the full raw log tail at the end
```

Output sections, in order:

1. **Deployed image** — `IMAGE_TAG` from the VPS's `.env` plus
   `docker compose ps worker-render`, so you know exactly which commit is
   running before trusting anything else below.
2. **Recent stage events** — greps the log window for the pipeline's
   structured lifecycle events (`stage_started`, `stage_succeeded`,
   `stage_failed`, `stage_needs_input`, `stage_skipped_cancelled`,
   `stage_execution_duplicate_delivery`, `stage_cache_hit`) with the
   `docker compose logs` service-name prefix stripped, so you can scan
   run/execution IDs and attempts at a glance. If nothing shows up, widen
   the window with `--log-lines` or `--since`.
3. **Container resource usage** — one-shot `docker stats` for the
   `worker-render` container. High CPU% here means it's actively working;
   near-zero with no ffmpeg process below means something's actually stuck
   (or idle, waiting for a new task).
4. **Live ffmpeg process(es)** — `docker top` on the container (not
   `docker exec ... ps aux` — the worker image has no `ps` binary, that
   fails silently). For each ffmpeg process found, prints a best-guess
   **phase** label inferred from its output filename
   (`server/apps/pipelines/stages/assembly.py`'s temp-file naming:
   `mezz_*.mp4` → per-scene mux, `*_concat.mp4` → chapter concat/transition,
   `final.mp4` → final pass), plus the raw PID/elapsed-time/CPU%/full
   command line. No ffmpeg process at all means it's between steps, doing
   non-ffmpeg work (asset fetch, DB I/O), or genuinely idle.
5. **Raw logs** (only with `--raw-logs`) — the full fetched log window,
   for when the grepped stage-events summary isn't enough.

If `worker-render` isn't running at all, it says so and exits `1`.

---

## `vps-taskiq-status.sh`

Combined incident report for the whole async (TaskIQ + RabbitMQ) pipeline
— broader than `vps-render-status.sh`, which is scoped to one worker's
current ffmpeg job. Read-only.

```bash
./scripts/vps-taskiq-status.sh              # full report, including logs
./scripts/vps-taskiq-status.sh --no-logs    # skip the log tails (faster)
```

Prints:
1. Deployed `IMAGE_TAG`.
2. `docker compose ps` for `scheduler`, `worker-api`, `worker-render`, `web`.
3. **RabbitMQ queue status** — connects to RabbitMQ directly (via a Python
   one-liner run inside the `web` container) and reports message/consumer
   counts for the `api` and `render` queues.
4. **Django pipeline state** — counts of active `PipelineRun`/
   `StageExecution` rows by status, plus the 5 most-recently-updated active
   runs and 10 most-recently-updated active stages (id, status,
   `updated_at`).
5. (Unless `--no-logs`) last 40 lines each of `worker-api` and
   `worker-render` logs, and last 20 of `scheduler`.

**Exit code doubles as a health check**: `0` if queues are empty and no
active runs/stages exist (idle); `1` if there's queued work or anything
in-flight. Useful in a loop / CI gate, not just for humans.

---

## `vps-taskiq-restart.sh`

Soft restart of the async path only — `scheduler`, `worker-api`,
`worker-render`. Does **not** touch RabbitMQ queues or Django DB state, so
anything mid-flight resumes (or redelivers) after the restart rather than
being lost.

```bash
./scripts/vps-taskiq-restart.sh
```

Use this for "a worker looks wedged, kick it" without wanting to lose
queued/in-flight work. If that's not enough — queues are stuck, DB rows
are stuck `RUNNING` with nothing actually processing them — escalate to
`vps-taskiq-reset.sh`.

---

## `vps-taskiq-reset.sh`

**Destructive.** Full async reset: stops `scheduler`/`worker-api`/
`worker-render`, deletes the RabbitMQ `api` and `render` queues (plus
their dead-letter/delay queues and exchanges), cancels every active
`PipelineRun`/`StageExecution` row in Django (marks them `CANCELLED`), then
restarts the async services clean.

```bash
./scripts/vps-taskiq-reset.sh          # prints current state, prompts for confirmation
./scripts/vps-taskiq-reset.sh --yes    # skip the confirmation prompt (e.g. for scripting)
```

It does **not** touch `web`, `caddy`, images, volumes, or `.env`.

Before wiping anything, it prints the current container states, queue
status, and DB status so you can see what you're about to lose. Without
`--yes`, you must type `reset` at the prompt to proceed. Afterward it
re-prints queue/DB status and exits `0` if things settled to idle, `1` if
active work is somehow still detected.

Use this when queues/DB rows are stuck in a way `vps-taskiq-restart.sh`
doesn't fix — e.g. messages wedged in RabbitMQ that keep getting
redelivered to a bad state, or `StageExecution` rows stuck `RUNNING` with
no process actually working on them. **Every in-flight pipeline run gets
cancelled** — users will need to re-trigger their runs afterward.

---

## `vps-restart.sh`

Restart one service (or everything) via `docker compose restart` — no
image pull, no migrations. For "it's stuck, kick it" on a *specific*
non-async service (e.g. `web` or `caddy`). For the async path specifically,
prefer `vps-taskiq-restart.sh` (it restarts the same three services this
would with `worker`, more explicitly named). For an actual redeploy with
new code, push to `main` and let the CI Deploy workflow handle it — this
script intentionally does not pull new images.

```bash
./scripts/vps-restart.sh            # restart everything
./scripts/vps-restart.sh web        # restart just web
```

Runs `docker compose restart <service>` then `docker compose ps <service>`
so you can confirm it came back up.

---

## `vps-logs.sh`

Tail `docker compose logs` for one service or all of them, over SSH, with
a TTY (so `-f` follow mode / Ctrl-C works as expected).

```bash
./scripts/vps-logs.sh                          # follow all services, from the last 200 lines
./scripts/vps-logs.sh worker-render             # follow just worker-render
./scripts/vps-logs.sh worker-render --since 1h  # last hour, then keep following
./scripts/vps-logs.sh caddy --no-follow --tail=500
```

Argument parsing: the first bare (non-flag) argument is treated as the
service name; everything else is passed straight through to
`docker compose logs` as extra args. Defaults to `--tail=200` if you don't
pass your own `--tail`/`--since`, and follows (`-f`) unless `--no-follow`
is given.

Valid service names match `docker-compose.vps.yml`: `web`, `scheduler`,
`bgutil-provider`, `worker-api`, `worker-render`, `caddy`.

---

## `vps-exec.sh`

Run an arbitrary one-off command inside a running service container, with
a TTY (so interactive commands like `manage.py shell` or `bash` work).

```bash
./scripts/vps-exec.sh web python manage.py shell
./scripts/vps-exec.sh web python manage.py trigger_test_task
./scripts/vps-exec.sh web bash
./scripts/vps-exec.sh worker-render bash
```

Requires at least a service name and a command — bare
`./scripts/vps-exec.sh web` will print usage and exit `1`.

This is the general escape hatch for anything the other scripts don't
cover — e.g. one-off Django shell queries, checking a file exists inside a
container, running a management command directly.

---

## `vps-setup-youtube.sh`

Uploads YouTube cookies to the VPS and wires the render worker to use
them for `yt-dlp` (needed because anonymous requests from the VPS's IP
get `LOGIN_REQUIRED` from YouTube's player API even for public videos).

```bash
./scripts/vps-setup-youtube.sh
```

Prerequisites:
- `scripts/vps.env` configured.
- `config/secrets/youtube-cookies.txt` must already exist — run
  [`export-youtube-cookies.sh`](#export-youtube-cookiessh) first.
- Optional: `YOUTUBE_DATA_API_KEY` set in your environment or in
  `config/.env`, for the API fallback path.

What it does, in order:
1. Creates `${VPS_APP_DIR}/secrets` on the VPS (`chmod 700`).
2. `scp`s the local cookie file there (`chmod 600`).
3. Upserts `YTDLP_COOKIE_FILE=/run/secrets/youtube-cookies.txt` into the
   VPS's `.env`.
4. If a `YOUTUBE_DATA_API_KEY` is available locally, upserts it into the
   VPS's `.env` too (otherwise skips with a note that metadata probing
   will rely on cookies only).
5. Copies the local `docker-compose.vps.yml` to
   `${VPS_APP_DIR}/docker-compose.yml` (picks up the cookie volume mount).
6. `docker compose pull worker-render && docker compose up -d worker-render`.
7. Verifies the cookie file actually exists inside the running container.

Cookies expire — re-run this whenever YouTube starts rejecting the
worker's requests again.

---

## `export-youtube-cookies.sh`

Local-only (no VPS/SSH involved) — exports YouTube cookies from a browser
on your machine for `yt-dlp`, as a prerequisite for
[`vps-setup-youtube.sh`](#vps-setup-youtubesh).

```bash
./scripts/export-youtube-cookies.sh            # defaults to firefox
./scripts/export-youtube-cookies.sh chrome     # or: safari, brave, edge
```

Requires a logged-in YouTube session in the chosen browser. Defaults to
Firefox on macOS specifically because Chrome rotates its cookie encryption
key on most logins, which breaks `yt-dlp`'s browser-cookie extraction.

Installs `yt-dlp` via `pip install --user` if it isn't already on `PATH`.
Writes `config/secrets/youtube-cookies.txt` (`chmod 600`, parent dir
`chmod 700` — this file is gitignored, never commit it) and does a quick
probe request against a known-public video to sanity-check the export
before declaring success. Fails loudly if the output file ends up empty.

---

## `create_dev_database.sql`

Not a script — raw SQL to bootstrap the **local** Postgres dev database
and superuser role. Not for VPS use.

```bash
psql -U postgres -f scripts/create_dev_database.sql
```

Creates the `reelforge` superuser role and a `reelforge`-owned `reelforge`
database (UTF-8). Typically only needed once per fresh local Postgres
instance — see the main `CLAUDE.md` / project setup docs for the full
local dev bring-up flow (`docker compose up -d`, `just run migrate`, etc.).

---

## `vps-lib.sh` / `vps-taskiq-lib.sh` (shared helpers, not run directly)

Sourced by the scripts above, not meant to be invoked on their own.

**`vps-lib.sh`** — loads `vps.env`, validates `VPS_HOST`/`VPS_USER` are
set (defaults `VPS_APP_DIR` to `/opt/reelforge` if unset), and defines:
- `vps_ssh <cmd>` — non-interactive SSH (`ConnectTimeout=10`).
- `vps_ssh_tty <cmd>` — SSH with a TTY allocated, for interactive commands.
- `vps_deployed_image_tag` — reads `IMAGE_TAG` from the VPS's `.env`
  (falling back to the running `web` container's image tag if absent).
- `vps_compose <args...>` — runs `docker compose <args>` on the VPS with
  `IMAGE_TAG` set from `vps_deployed_image_tag`.

**`vps-taskiq-lib.sh`** — sources `vps-lib.sh` and adds TaskIQ/RabbitMQ-
specific helpers used by the `vps-taskiq-*.sh` scripts: `taskiq_compose`,
`taskiq_stop_async` / `taskiq_start_async` / `taskiq_restart_async`,
`taskiq_print_queue_status`, `taskiq_delete_queues`,
`taskiq_print_db_status`, `taskiq_cancel_active_state`, and
`taskiq_detect_stuck` (returns non-zero if queues or active DB rows exist).
`TASKIQ_ASYNC_SERVICES=(scheduler worker-api worker-render)` is defined
here too.

You generally don't need to touch either file directly — but if you're
writing a new `vps-*.sh` script, source `vps-lib.sh` (or `vps-taskiq-lib.sh`
if it's RabbitMQ/Django-pipeline-state related) rather than reimplementing
SSH/compose plumbing.

---

## Troubleshooting

- **"Set VPS_HOST in scripts/vps.env..."** — you haven't done the
  one-time setup above; copy `vps.env.example` to `vps.env` and fill it in.
- **SSH connection refused/timeout** — confirm `ssh deploy@<vps-ip>` works
  standalone first; these scripts add nothing beyond a 10s connect timeout.
- **A script says a container isn't running** — check
  `./scripts/vps-status.sh` first for the whole-stack picture before
  digging into one service.
- **Something's stuck in the async pipeline** — escalation path:
  `vps-render-status.sh` / `vps-taskiq-status.sh` (diagnose, read-only) →
  `vps-taskiq-restart.sh` (soft kick) → `vps-taskiq-reset.sh` (nuclear,
  cancels active runs).
