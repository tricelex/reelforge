# RustFS Media Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add RustFS to the Docker Compose dev stack as the S3-compatible asset storage backend, auto-creating the `reelforge` bucket on startup, with the web UI accessible at port 9001.

**Architecture:** A `rustfs` service is added to `docker-compose.yml` alongside a one-shot `rustfs-init` container (`minio/mc`) that creates the bucket after RustFS passes its healthcheck. `web`, `worker`, and `scheduler` wait on `rustfs-init` completing. Django's existing `AssetStorage` (S3Boto3Storage) connects via `AWS_S3_ENDPOINT_URL`, which defaults to `http://rustfs:9000` in dev. Production points to an external server via env vars — no container change required.

**Tech Stack:** `rustfs/rustfs` Docker image, `minio/mc` init container, `django-storages` S3Boto3Storage (already wired), Docker Compose healthchecks.

---

### Task 1: Verify RustFS image conventions

**Files:**
- Read-only inspection — no file changes

The spec flags that RustFS env var names, healthcheck path, and startup command need verification before committing. Do this first.

- [ ] **Step 1: Pull the image and inspect**

```bash
docker pull rustfs/rustfs:latest
docker inspect rustfs/rustfs:latest | python3 -c "
import json, sys
d = json.load(sys.stdin)[0]['Config']
print('ENV:', d.get('Env'))
print('CMD:', d.get('Cmd'))
print('Entrypoint:', d.get('Entrypoint'))
print('Ports:', list(d.get('ExposedPorts', {}).keys()))
"
```

- [ ] **Step 2: Confirm or adjust these three things**

| Item | Expected | Adjust if different |
|------|----------|-------------------|
| Root user env var | `RUSTFS_ROOT_USER` | Replace in Task 2 service definition |
| Root password env var | `RUSTFS_ROOT_PASSWORD` | Replace in Task 2 service definition |
| S3 API port | `9000` | Update healthcheck URL and override port bindings |
| Console port | `9001` | Update `--console-address` flag and override port bindings |
| Startup command | `server /data --console-address ":9001"` | Adjust `command:` in Task 2 |

If RustFS exposes a different healthcheck endpoint (e.g. `/health` instead of `/minio/health/live`), note it for Task 2. If no HTTP healthcheck exists, replace with a TCP check:
```yaml
test: ["CMD-SHELL", "nc -z localhost 9000 || exit 1"]
```

---

### Task 2: Add rustfs service and volume to docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add the `rustfs` service**

In `docker-compose.yml`, insert after the `scheduler` service block (before `networks:`), using the env var names confirmed in Task 1:

```yaml
  rustfs:
    image: rustfs/rustfs:latest
    restart: unless-stopped
    networks:
      - backend-net
    volumes:
      - rustfs-data:/data
    environment:
      RUSTFS_ROOT_USER: ${AWS_ACCESS_KEY_ID:-minioadmin}
      RUSTFS_ROOT_PASSWORD: ${AWS_SECRET_ACCESS_KEY:-minioadmin}
    command: server /data --console-address ":9001"
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:9000/minio/health/live || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 5
      start_period: 10s

```

- [ ] **Step 2: Add `rustfs-data` to the top-level volumes block**

The `volumes:` block currently ends at line 127. Add one line:

```yaml
volumes:
  postgres-data:
  django-static:
  redis-data:
  rabbitmq-data:
  rustfs-data:
```

- [ ] **Step 3: Verify syntax**

```bash
docker compose config --quiet
```

Expected: no output (exit 0). If you see an error, fix the YAML indentation — all service-level keys are indented 2 spaces under the service name.

---

### Task 3: Add rustfs-init bucket creation service

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Insert `rustfs-init` after the `rustfs` service block**

```yaml
  rustfs-init:
    image: minio/mc:latest
    networks:
      - backend-net
    depends_on:
      rustfs:
        condition: service_healthy
    entrypoint: >
      /bin/sh -c "
        mc alias set local http://rustfs:9000
          $${AWS_ACCESS_KEY_ID:-minioadmin}
          $${AWS_SECRET_ACCESS_KEY:-minioadmin} &&
        mc mb --ignore-existing local/$${AWS_STORAGE_BUCKET_NAME:-reelforge}
      "
    restart: on-failure

```

Note the `$$` double-dollar escaping — Docker Compose requires this to pass a literal `$` to the shell (single `$` is consumed by Compose variable substitution).

- [ ] **Step 2: Verify syntax**

```bash
docker compose config --quiet
```

Expected: no output (exit 0).

---

### Task 4: Wire rustfs-init dependency into web, worker, scheduler

**Files:**
- Modify: `docker-compose.yml` (three `depends_on` blocks)

The `web` service's `depends_on` lives inside the `&web` YAML anchor (lines 71–77). `worker` and `scheduler` each override `depends_on` with their own explicit blocks (lines 94–100 and 108–114). All three need `rustfs-init` added.

- [ ] **Step 1: Update the `&web` anchor `depends_on` (used by `web`)**

Find this block (around line 71):
```yaml
      depends_on:
        db:
          condition: service_healthy
        redis:
          condition: service_healthy
        rabbitmq:
          condition: service_healthy
```

Replace with:
```yaml
      depends_on:
        db:
          condition: service_healthy
        redis:
          condition: service_healthy
        rabbitmq:
          condition: service_healthy
        rustfs-init:
          condition: service_completed_successfully
```

- [ ] **Step 2: Update `worker`'s `depends_on` (around line 94)**

Find:
```yaml
  worker:
    <<: *web
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
```

Replace with:
```yaml
  worker:
    <<: *web
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
      rustfs-init:
        condition: service_completed_successfully
```

- [ ] **Step 3: Update `scheduler`'s `depends_on` (around line 108)**

Find:
```yaml
  scheduler:
    <<: *web
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
```

Replace with:
```yaml
  scheduler:
    <<: *web
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
      rustfs-init:
        condition: service_completed_successfully
```

- [ ] **Step 4: Verify final config**

```bash
docker compose config --quiet
```

Expected: no output (exit 0).

- [ ] **Step 5: Commit all docker-compose.yml changes**

```bash
git add docker-compose.yml
git commit -m "feat(infra): add RustFS service and auto-bucket-creation init container"
```

---

### Task 5: Add RustFS port bindings to docker-compose.override.yml

**Files:**
- Modify: `docker-compose.override.yml`

The override file is dev-only and automatically picked up by `docker compose up`. Port `9000` exposes the S3 API for local SDK access (e.g. `just run` commands that need direct object storage access). Port `9001` exposes the web UI console.

- [ ] **Step 1: Add rustfs port bindings**

In `docker-compose.override.yml`, add after the `scheduler:` block (before the end of file):

```yaml
  rustfs:
    ports:
      - "9000:9000"   # S3 API
      - "9001:9001"   # Web UI console
```

- [ ] **Step 2: Verify**

```bash
docker compose config --quiet
```

Expected: no output (exit 0).

- [ ] **Step 3: Commit**

```bash
git add docker-compose.override.yml
git commit -m "feat(infra): expose RustFS S3 API and web UI ports in dev"
```

---

### Task 6: Update storage settings and env template

**Files:**
- Modify: `server/settings/components/storage.py`
- Modify: `config/.env.template`

- [ ] **Step 1: Update the default S3 endpoint in storage.py**

In `server/settings/components/storage.py`, find:
```python
AWS_S3_ENDPOINT_URL: str = config(
    'AWS_S3_ENDPOINT_URL',
    default='http://minio:9000',
)
```

Replace with:
```python
AWS_S3_ENDPOINT_URL: str = config(
    'AWS_S3_ENDPOINT_URL',
    default='http://rustfs:9000',
)
```

- [ ] **Step 2: Add storage section to config/.env.template**

At the end of `config/.env.template`, append:

```dotenv


# === Storage (RustFS / S3-compatible) ===

# Dev defaults (minioadmin / http://rustfs:9000) are baked into
# server/settings/components/storage.py — only set these for staging/production.
AWS_ACCESS_KEY_ID=__CHANGEME__
AWS_SECRET_ACCESS_KEY=__CHANGEME__
AWS_STORAGE_BUCKET_NAME=reelforge
AWS_S3_ENDPOINT_URL=https://your-rustfs-server.example.com
AWS_S3_VERIFY=true
```

- [ ] **Step 3: Commit**

```bash
git add server/settings/components/storage.py config/.env.template
git commit -m "feat(storage): point default S3 endpoint to rustfs; document prod env vars"
```

---

### Task 7: Smoke test the full stack

**Files:**
- No file changes — verification only

- [ ] **Step 1: Bring up the stack**

```bash
docker compose up -d
```

Watch the startup order: `rustfs` should become healthy before `rustfs-init` runs, and `rustfs-init` should exit 0 before `web`/`worker`/`scheduler` start.

- [ ] **Step 2: Check all services are up**

```bash
docker compose ps
```

Expected: all services `Up` or `Exited (0)`. `rustfs-init` should show `Exited (0)`.

If `rustfs-init` shows `Exited (1)`, check logs:
```bash
docker compose logs rustfs-init
```

Common causes:
- Wrong env var name for root credentials (revisit Task 1 findings)
- RustFS not yet ready despite healthcheck (try increasing `start_period` to `15s`)

- [ ] **Step 3: Verify the bucket was created**

```bash
docker compose run --rm rustfs-init /bin/sh -c "
  mc alias set local http://rustfs:9000 \${AWS_ACCESS_KEY_ID:-minioadmin} \${AWS_SECRET_ACCESS_KEY:-minioadmin} &&
  mc ls local/
"
```

Expected output includes `reelforge/` in the listing.

- [ ] **Step 4: Access the web UI**

Open http://localhost:9001 in a browser. Log in with `minioadmin` / `minioadmin`. Confirm the `reelforge` bucket is listed.

- [ ] **Step 5: Run the test suite to confirm no regressions**

```bash
docker compose exec web pytest --no-cov
```

Expected: all tests pass. Storage tests use `FileSystemStorage` override so no S3 connection is needed.

- [ ] **Step 6: Tear down and bring back up to confirm idempotency**

```bash
docker compose down
docker compose up -d
docker compose ps
```

Expected: same healthy state. `rustfs-init` runs again but `mc mb --ignore-existing` means it exits 0 even though the bucket already exists.
