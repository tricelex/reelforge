export COMPOSE_FILE := "docker-compose.local.yml"

## Just does not yet manage signals for subprocesses reliably, which can lead to unexpected behavior.
## Exercise caution before expanding its usage in production environments.
## For more information, see https://github.com/casey/just/issues/2473 .


# Default command to list all available commands.
default:
    @just --list

# infra: Start only Postgres and Redis in Docker (infrastructure only, no app containers).
infra:
    @echo "Starting infrastructure (Postgres + Redis)..."
    @docker compose up -d postgres redis

# dotenv: Regenerate .env.local by merging env files (local .host overrides win on duplicate keys).
dotenv:
    #!/usr/bin/env bash
    awk -F'=' '/^[A-Za-z]/ { if (!seen[$1]++) print }' \
        .envs/.local/.host .envs/.local/.django .envs/.local/.postgres > .env.local

# migrate: Run Django migrations against local Postgres.
migrate: dotenv
    #!/usr/bin/env bash
    set -a; source .env.local; set +a
    exec uv run python manage.py migrate

# purge: Purge all pending Celery task messages from Redis queues.
purge: dotenv
    #!/usr/bin/env bash
    set -a; source .env.local; set +a
    exec uv run celery -A config.celery_app purge -f

# dev: Run all processes together via Procfile (all logs in one terminal).
dev: infra dotenv
    #!/usr/bin/env bash
    set -euo pipefail
    set -a; source .env.local; set +a
    uv run python manage.py migrate
    uv run honcho start -e .env.local

# dev-web: Django dev server — run in its own terminal tab.
dev-web: dotenv
    #!/usr/bin/env bash
    set -a; source .env.local; set +a
    exec uv run python manage.py runserver_plus 0.0.0.0:8000

# dev-worker: Celery worker — run in its own terminal tab.
dev-worker: dotenv
    #!/usr/bin/env bash
    set -a; source .env.local; set +a
    exec uv run celery -A config.celery_app worker -l INFO -Q default,orchestration,research,clipping,rendering,uploads,analytics

# dev-beat: Celery beat scheduler — run in its own terminal tab.
dev-beat: dotenv
    #!/usr/bin/env bash
    set -a; source .env.local; set +a
    rm -f celerybeat.pid
    exec uv run celery -A config.celery_app beat -l INFO

# dev-flower: Flower monitor (http://localhost:5555) — run in its own terminal tab.
dev-flower: dotenv
    #!/usr/bin/env bash
    set -a; source .env.local; set +a
    exec uv run celery -A config.celery_app flower --basic_auth="${CELERY_FLOWER_USER}:${CELERY_FLOWER_PASSWORD}"

# dev-stop: Stop Docker infrastructure services.
dev-stop:
    @echo "Stopping infrastructure..."
    @docker compose stop postgres redis

# build: Build python image.
build *args:
    @echo "Building python image..."
    @docker compose build {{args}}

# up: Start up containers.
up:
    @echo "Starting up containers..."
    @docker compose up -d --remove-orphans

# debug: Start containers with debugpy remote attach (Django: 5678, Celery: 5679).
debug:
    @echo "Starting up containers in debug mode..."
    @COMPOSE_FILE="docker-compose.local.yml:docker-compose.debug.yml" docker compose up -d --remove-orphans

# down: Stop containers.
down:
    @echo "Stopping containers..."
    @docker compose down

# prune: Remove containers and their volumes.
prune *args:
    @echo "Killing containers and removing volumes..."
    @docker compose down -v {{args}}

# logs: View container logs
logs *args:
    @docker compose logs -f {{args}}

# manage: Executes `manage.py` inside Docker (requires containers running).
manage +args:
    @docker compose run --rm django python ./manage.py {{args}}

# run: Executes `manage.py` locally against Docker Postgres/Redis (no app container needed).
run +args: dotenv
    #!/usr/bin/env bash
    set -a; source .env.local; set +a
    exec uv run python manage.py {{args}}

create-superuser:
    @docker compose run --rm django python ./manage.py createsuperuser

# tailwind-build: Compile Tailwind CSS once.
tailwind-build:
    @echo "Building Tailwind CSS..."
    @./bin/tailwindcss --input reelforge/ui/static/ui/css/input.css --output reelforge/static/css/tailwind.css --content "./reelforge/**/templates/**/*.html" --minify

# tailwind-watch: Watch and recompile Tailwind CSS on template changes.
tailwind-watch:
    @echo "Watching Tailwind CSS..."
    @./bin/tailwindcss --input reelforge/ui/static/ui/css/input.css --output reelforge/static/css/tailwind.css --content "./reelforge/**/templates/**/*.html" --watch

# lint: Run ruff linting checks.
lint:
    @echo "Running ruff linting checks..."
    @uv run ruff check . --unsafe-fixes

# format: Run ruff code formatting.
format:
    @echo "Running ruff code formatting..."
    @uv run ruff format .

# format-check: Check if code is formatted correctly without making changes.
format-check:
    @echo "Checking code formatting..."
    @uv run ruff format --check .

# precommit: Run all pre-commit hooks on all files.
precommit:
    @echo "Running pre-commit hooks on all files..."
    @uv run pre-commit run --all-files

# test: Run tests using pytest on the host (requires Docker containers to be running for DB).
test +args:
    @echo "Running tests..."
    @DATABASE_URL="postgres://iWlkarZJuZGrMUoUridGOMxfeYdFOFPC:dxvRAIPjs24iALAGDDCgpcnx2utkTlyjvPpJ3JxfekUm1M2M9qv6aynQyaGwZgZL@localhost:5435/reelforge" \
    CREDENTIAL_ENCRYPTION_KEY="SQWkV11cGKrYsGrGfy8by0S3lCB7W-Z4x0hquqew0Es=" \
    uv run pytest {{args}}

# test-coverage: Run tests and generate coverage report.
test-coverage:
    @echo "Running tests with coverage..."
    @DATABASE_URL="postgres://iWlkarZJuZGrMUoUridGOMxfeYdFOFPC:dxvRAIPjs24iALAGDDCgpcnx2utkTlyjvPpJ3JxfekUm1M2M9qv6aynQyaGwZgZL@localhost:5435/reelforge" \
    CREDENTIAL_ENCRYPTION_KEY="SQWkV11cGKrYsGrGfy8by0S3lCB7W-Z4x0hquqew0Es=" \
    uv run coverage run -m pytest
    @uv run coverage report
    @uv run coverage html
    @echo "HTML coverage report generated in htmlcov/index.html"
