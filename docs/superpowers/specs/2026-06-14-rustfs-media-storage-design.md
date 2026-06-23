# RustFS Media Storage — Design Spec

**Date:** 2026-06-14
**Status:** Approved

## Overview

Add RustFS (S3-compatible object storage) to the Docker Compose development stack and wire it in as Django's default media/asset storage backend. Production connects to an external RustFS server via environment variables.

## Context

`server/settings/components/storage.py` and `server/common/s3.py` are already written for S3-compatible storage using `django-storages` / `S3Boto3Storage`. No object storage service exists in Docker Compose yet — the settings reference `http://minio:9000` as the default endpoint, which will be updated to `http://rustfs:9000`.

Tests already override to `FileSystemStorage` via `tests/plugins/django_settings.py` — no test changes needed.

## Architecture

```
docker compose up
  └── rustfs          (S3 API :9000, Web UI :9001)
  └── rustfs-init     (one-shot: mc alias set + mc mb --ignore-existing)
  └── web / worker / scheduler
        depends_on rustfs-init: service_completed_successfully
```

Django's `AssetStorage` (S3Boto3Storage) connects to RustFS via `AWS_S3_ENDPOINT_URL`. In dev this resolves to `http://rustfs:9000` (Docker network). In production, env vars point to the external RustFS server.

## Components

### 1. `docker-compose.yml` — rustfs service

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
    test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
    interval: 5s
    timeout: 5s
    retries: 5
    start_period: 10s
```

### 2. `docker-compose.yml` — rustfs-init service

One-shot container using `minio/mc` to create the bucket after RustFS is healthy.

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
    mc alias set rustfs http://rustfs:9000
      $${AWS_ACCESS_KEY_ID:-minioadmin}
      $${AWS_SECRET_ACCESS_KEY:-minioadmin} &&
    mc mb --ignore-existing rustfs/${AWS_STORAGE_BUCKET_NAME:-***REMOVED***}
    "
  restart: on-failure
```

### 3. `docker-compose.yml` — web/worker/scheduler dependency

Add to all three services:

```yaml
depends_on:
  rustfs-init:
    condition: service_completed_successfully
```

### 4. `docker-compose.override.yml` — port bindings

```yaml
rustfs:
  ports:
    - "9000:9000"   # S3 API (for local SDK access and just run commands)
    - "9001:9001"   # Web UI console
```

### 5. `docker-compose.yml` — volumes

Add `rustfs-data:` to the top-level `volumes` block.

### 6. `server/settings/components/storage.py`

Change default endpoint:

```python
AWS_S3_ENDPOINT_URL: str = config(
    'AWS_S3_ENDPOINT_URL',
    default='http://rustfs:9000',
)
```

Default credentials stay as `minioadmin` for dev convenience.

### 7. `config/.env.template` — production storage vars

```dotenv
# === Storage (RustFS / S3-compatible) ===
# Dev defaults are baked into storage.py settings (minioadmin / http://rustfs:9000).
# Set these for staging/production to point at the external RustFS server.
AWS_ACCESS_KEY_ID=***REMOVED***
AWS_SECRET_ACCESS_KEY=***REMOVED***
AWS_STORAGE_BUCKET_NAME=***REMOVED***
AWS_S3_ENDPOINT_URL=***REMOVED***
AWS_S3_VERIFY=true
```

## Data Flow

1. `docker compose up` starts `rustfs` then `rustfs-init` (waits for healthcheck).
2. `rustfs-init` creates the `***REMOVED***` bucket and exits 0.
3. `web`/`worker`/`scheduler` start once `rustfs-init` completes successfully.
4. Django's `AssetStorage` (configured via `STORAGES['default']`) connects to `http://rustfs:9000`.
5. File uploads → RustFS bucket `/assets/` prefix (set in `AssetStorage.location`).

## Error Handling

- `rustfs-init` has `restart: on-failure` — retries if RustFS isn't yet ready despite the healthcheck (race condition safety net).
- `AWS_S3_VERIFY=False` in dev (self-signed / no TLS); `True` in production.

## Production

No RustFS container in production — the external server is accessed purely via env vars. The `docker/docker-compose.prod.yml` file requires no changes.

## Implementation Notes

RustFS is newer than MinIO and its Docker image conventions should be verified at implementation time:

- **Env vars:** `RUSTFS_ROOT_USER` / `RUSTFS_ROOT_PASSWORD` — confirm against `docker inspect rustfs/rustfs` or image docs before committing.
- **Healthcheck path:** `/minio/health/live` is the MinIO endpoint; RustFS may expose a different path (e.g. `/health` or no liveness endpoint). Fall back to a TCP check if needed.
- **Startup command:** `server /data --console-address ":9001"` mirrors MinIO's CLI; confirm RustFS uses the same flags.

If any of these differ, update the service definition accordingly — the rest of the design (Django settings, `mc` init container, port bindings) is unaffected.

## Not In Scope

- Presigned URL generation (already handled by `AssetStorage.default_acl = None`)
- CORS configuration on the RustFS bucket
- Lifecycle policies / bucket versioning
