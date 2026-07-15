# VPS operations guide

Day-2 operations for the deployment set up in
[vps-deployment-guide.md](./vps-deployment-guide.md): checking logs, running one-off commands,
restarting a stuck service, and diagnosing the most common failure modes.

## Setup (one-time, per laptop)

```bash
cp scripts/vps.env.example scripts/vps.env
# edit scripts/vps.env: set VPS_HOST to your VPS's IP, VPS_USER=deploy
```

`scripts/vps.env` is gitignored — it's local connection config, not a secret store. All scripts
below use your own SSH key (the one already in `deploy`'s `authorized_keys` from bootstrap step 1),
so no passwords or extra keys are needed.

## Scripts

| Script | What it does |
|---|---|
| `./scripts/vps-status.sh` | One-shot snapshot: container states, CPU/mem per container, disk usage, swap, health endpoint |
| `./scripts/vps-logs.sh [service] [args]` | Tail logs — all services or one, follows by default |
| `./scripts/vps-exec.sh <service> <cmd...>` | Run a command inside a running container (shell, management command, etc.) |
| `./scripts/vps-restart.sh [service]` | Restart one service (or all) without pulling new images |

None of these touch `.env`, migrations, or images — they're for looking and poking, not deploying.
For an actual code change, push to `main` and let `.github/workflows/deploy.yml` handle it.

---

## Common scenarios

### "Is everything up?"

```bash
./scripts/vps-status.sh
```

All four services should show `Up` (or `Up (healthy)` for `web`). Health endpoint should return
`HTTP 200`.

### "The site is down / returning 502"

```bash
./scripts/vps-logs.sh caddy --tail=100 --no-follow
./scripts/vps-logs.sh web --tail=100 --no-follow
```

- Caddy logs showing repeated TLS/ACME errors → DNS or Let's Encrypt rate-limit issue, see the
  deployment guide's DNS section.
- Caddy up but `web` not responding → check `web`'s logs for a startup crash (bad env var, DB
  unreachable, etc.) and confirm the healthcheck: `./scripts/vps-exec.sh web sh /code/docker/django/healthcheck.sh`.

### "Clips/videos aren't processing — worker seems stuck"

```bash
./scripts/vps-logs.sh worker --tail=200
```

Look for repeated tracebacks (crash-looping) vs. silence (nothing being consumed — check RabbitMQ
queue depth in Coolify's RabbitMQ management UI). If it's crash-looping on a specific task, the
container is likely OOMing on that job — see the memory section below before assuming it's a code
bug. If it's just wedged, a restart is a fine first move:

```bash
./scripts/vps-restart.sh worker
```

### Transcription + diarization (ElevenLabs Scribe hosted API)

Transcription and speaker diarization run together against ElevenLabs' Scribe v2 hosted
API (`ELEVENLABS_API_KEY`), not a local model — there's no HuggingFace model cache,
GPU/CPU inference, or subprocess pool on the worker to manage. `ClipTranscribeStage`
extracts mono 16kHz audio with `ffmpeg`, uploads it via `elevenlabs.transcribe()`
(`diarize=true`), and gets back a word-level transcript with a `speaker_id` on every word
in one response — there's no separate diarization stage or job to poll.

**Expectations:**

- No model download/cache warmup — the first request is as fast as any other.
- A stuck or slow call is bounded by `ClipTranscribeStage.timeout_s` (3600s), same as
  every other pipeline stage — no bespoke diarization timeout to configure.
- Missing/blank `ELEVENLABS_API_KEY` fails fast with `error_code=missing_api_key` rather
  than attempting the call.
- `clip_analyze` no longer does any diarization work — it only reads the already-diarized
  `enriched_transcript` off the manifest asset produced by `clip_transcribe`.

### Forced alignment (ElevenLabs hosted API)

Longform caption timing uses ElevenLabs Forced Alignment
(`POST /v1/forced-alignment`) with the same `ELEVENLABS_API_KEY` as TTS/Scribe —
not a local torchaudio/WhisperX model. `AlignmentStage` uploads each TTS chapter
MP3 plus the known script text and gets word-level timestamps back. The stage runs
on the `api` queue (HTTP), not `gpu`.

**Expectations:**

- Existing blueprints that still list `alignment` on `queue: gpu` should be re-seeded
  (`python manage.py seed_blueprints`) so new runs land on the `api` worker.
- Pricing matches Scribe STT (per audio minute).
- Missing/blank `ELEVENLABS_API_KEY` fails fast with `error_code=missing_api_key`.

### "High memory usage / suspected OOM"

```bash
./scripts/vps-status.sh   # docker stats section shows per-container memory
```

On the VPS itself, confirm whether the kernel actually OOM-killed something:

```bash
./scripts/vps-exec.sh web bash   # or ssh in directly
dmesg -T | grep -i 'out of memory' | tail -20
```

`worker` has a 7GB `mem_limit` in `docker-compose.vps.yml` — if it's consistently maxing that out,
either the workload genuinely needs more headroom (bump `mem_limit`, VPS has 12GB total) or dial
concurrency down further via `TASKIQ_MAX_ASYNC_TASKS=1` in `/opt/reelforge/.env` (defaults to `2`),
then `docker compose up -d worker`.

### "I need a Django shell / need to run a management command"

```bash
./scripts/vps-exec.sh web python manage.py shell
./scripts/vps-exec.sh web python manage.py trigger_test_task   # broker/worker smoke test
./scripts/vps-exec.sh web python manage.py <any other command>
```

### "I need a raw shell inside a container"

```bash
./scripts/vps-exec.sh web bash
./scripts/vps-exec.sh worker bash
```

### "Disk is filling up"

```bash
./scripts/vps-status.sh   # shows df -h and docker system df
```

Docker log rotation is already configured (10MB × 3 files per container, from
`scripts/vps-bootstrap.sh`), so runaway logs shouldn't be the cause. Usual suspects: old images
piling up (the deploy workflow already runs `docker image prune -af --filter 'until=72h'` after
every deploy, so this is mostly self-cleaning) or the 8GB swapfile being confused for "real" disk
usage in `df` output (it's not reclaimable space, that's expected).

If you do need to reclaim space manually:

```bash
# on the VPS — safe, only removes dangling/unused images, not volumes
docker image prune -af
```

Do **not** run `docker system prune --volumes` or `docker volume prune` — that would delete the
`caddy-data` volume (your TLS certificates), forcing Caddy to re-request them from Let's Encrypt.

### "What image/commit is currently deployed?"

```bash
./scripts/vps-exec.sh web python manage.py --version   # sanity check the container is responsive
```

or, more directly:

```bash
ssh deploy@<VPS_IP> "cd /opt/reelforge && docker compose images"
```

The tag shown is the git SHA (see the deployment guide's rollback section) unless it fell back to
`latest`.

### "Something's wrong and I want to see everything at once"

```bash
./scripts/vps-logs.sh   # all services, follows live — Ctrl-C to stop
```

---

## When scripts aren't enough

Everything here is a thin wrapper around plain `ssh` + `docker compose`. If a script doesn't fit
what you need, just SSH in directly and run the same commands yourself:

```bash
ssh deploy@<VPS_IP>
cd /opt/reelforge
docker compose ps
docker compose logs -f <service>
docker compose exec <service> <command>
docker compose restart <service>
```
