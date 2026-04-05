# CLAUDE.md — Reelforge Project Memory

> This file is the authoritative reference for Claude Code when working on this project.
> Read this fully before writing any code. Every decision made here was deliberate.

---

## WORKFLOW — SUPERPOWERS SKILLS

This project uses the **Superpowers** Claude Code plugin. Before starting any non-trivial task, invoke the appropriate skill:

| Situation | Skill to invoke |
|---|---|
| New feature / idea to build | `superpowers:brainstorming` |
| Writing an implementation plan | `superpowers:writing-plans` |
| Executing a plan from `docs/superpowers/plans/` | `superpowers:executing-plans` |
| Setting up an isolated branch to work in | `superpowers:using-git-worktrees` |
| Finishing a feature branch | `superpowers:finishing-a-development-branch` |

Worktrees live in `.worktrees/` (gitignored). Plans live in `docs/superpowers/plans/`. Specs live in `docs/superpowers/specs/`.

---

## IMPLEMENTATION STATUS

**Current State**: ✅ **Substantial pipeline + operator dashboard in place**

**What Works Today:**
- Full Django 5.2 project with all core apps (channels, research, scripts, assets, production, distribution, pipeline, clipping, ui)
- Multi-channel YouTube automation pipeline (FSM-orchestrated, Celery-driven)
- Clipping feature: analyze → render → review dashboard
- Operator dashboard (`/app/`) — job list, job detail, clip candidate config, render progress
- Admin interface (Unfold theme) for all models
- Docker Compose development environment
- Pre-commit hooks: Ruff, djlint, mypy

**Apps in `reelforge/`:**
- `core/` — abstract base models, validators, storage helpers
- `channels/` — Channel model, YouTube OAuth credentials
- `research/` — ResearchJob, TopicIdea
- `scripts/` — ScriptJob, ScriptRevision
- `assets/` — AssetJob, VoiceoverRun, ImageGenerationRun, etc.
- `production/` — SceneBreakdownJob, AudioMixJob, ProductionJob
- `distribution/` — DistributionJob
- `pipeline/` — PipelineRun, PipelineEvent (FSM orchestration)
- `clipping/` — ClipCandidate, ClipRender, ClipLayoutConfig, ClipStyleConfig, ClipTimedOverlay
- `ui/` — Dashboard views, base templates (Tailwind + HTMX + Alpine.js)
- `agents/` — OpenAI Agents SDK agent definitions
- `services/` — Provider abstractions, media processing (audio/video/image)
- `users/` — Custom User model (cookiecutter default)

---

## PART I: QUICK START

### 1. Tech Stack

- **Django 5.2** + DRF + Celery + PostgreSQL (psycopg3) + Redis
- **Python 3.13**, dependency management via `uv`
- **Docker Compose** for all services (run `just up`)
- **Tailwind CSS v4** (binary at `bin/tailwindcss`, compiled to `reelforge/static/css/tailwind.css`)
- **HTMX 2.0.4** + **Alpine.js 3.14** for operator UI (no separate frontend build beyond Tailwind)
- **Unfold** admin theme

### 2. Running Tests

Tests are run **from the host machine** against the Docker Postgres instance (port 5435):

```bash
# Standard test run — use real DB credentials from .envs/.local/.postgres
DATABASE_URL="postgres://iWlkarZJuZGrMUoUridGOMxfeYdFOFPC:dxvRAIPjs24iALAGDDCgpcnx2utkTlyjvPpJ3JxfekUm1M2M9qv6aynQyaGwZgZL@localhost:5435/reelforge" \
CREDENTIAL_ENCRYPTION_KEY="SQWkV11cGKrYsGrGfy8by0S3lCB7W-Z4x0hquqew0Es=" \
uv run pytest

# Single test / subset
DATABASE_URL="..." CREDENTIAL_ENCRYPTION_KEY="..." uv run pytest reelforge/clipping/tests/ -v
DATABASE_URL="..." CREDENTIAL_ENCRYPTION_KEY="..." uv run pytest path/to/test.py::test_name -v

# Type checking
uv run mypy reelforge

# Linting / formatting
uv run ruff check . --unsafe-fixes
uv run ruff format .
```

**The Postgres credentials never change** — they're in `.envs/.local/.postgres` (gitignored). Always use port **5435** (Docker mapped port, not 5432).

### 3. Docker / Just Commands

Docker is managed via `just` (see `justfile`):

```bash
just up                # Start all Docker services
just down              # Stop containers
just build             # Rebuild images
just prune             # Remove containers + volumes
just logs [service]    # Follow logs
just manage <cmd>      # Run manage.py inside Django container
just tailwind-build    # Compile Tailwind CSS (minified)
just tailwind-watch    # Watch + recompile Tailwind on change
just lint              # ruff check
just format            # ruff format
just precommit         # Run all pre-commit hooks
```

**Docker services:**
- `django` — Django app (port 8000)
- `postgres` — PostgreSQL (mapped to host port 5435)
- `redis` — Redis (port 6379)
- `celeryworker` — Celery worker
- `celerybeat` — Celery beat scheduler
- `flower` — Celery monitoring (port 5555)
- `mailpit` — Email testing (port 8025)

Environment files: `.envs/.local/` (local) and `.envs/.production/` (production). **Never commit these.**

### 4. Migrations

Always run makemigrations from the Docker container (access to the running DB):

```bash
just manage makemigrations <app> --name <descriptive_name>
just manage migrate
```

Or from the host using the real credentials:

```bash
DATABASE_URL="postgres://...@localhost:5435/reelforge" \
CREDENTIAL_ENCRYPTION_KEY="..." \
uv run python manage.py makemigrations <app> --name <descriptive_name>
```

**Never use placeholder/fake DB URLs for makemigrations** — Django needs to inspect the real schema.

### 5. Tailwind CSS

Tailwind binary lives at `bin/tailwindcss`. Run `just tailwind-build` before committing template changes. The compiled output at `reelforge/static/css/tailwind.css` **is** committed to git (it's served as a static file).

---

## PART II: ARCHITECTURE

### 1. What We Are Building

**Reelforge** is a multi-channel YouTube automation SaaS — manages the full lifecycle from research to analytics for multiple channels simultaneously. The operator runs everything from the Django admin + a lightweight operator dashboard (`/app/`).

### 2. The Pipeline Flow

```
Channel Config
     │
     ▼
[RESEARCHING]       ResearchAgent discovers topics
     │
     ▼
[SCRIPTING]         ScriptAgent writes script + hooks + SEO metadata
     │
     ▼
[AWAITING_APPROVAL] Operator reviews in admin (or auto-approves)
     │
     ▼
[GENERATING_ASSETS] AssetAgent: voiceover (ElevenLabs), images (Fal.ai), music, thumbnails
     │
     ▼
[RENDERING]         VideoRenderer: MoviePy + FFmpeg encode
     │
     ▼
[QA]                VideoQA: 9 automated checks
     │
     ▼
[UPLOADING]         YouTube upload + thumbnail + chapters + Shorts
     │
     ▼
[PUBLISHED]         Analytics polling → feeds back into research
```

### 3. Clipping Feature

The clipping feature is a separate pipeline for taking existing video content and turning it into social clips:

```
ClippingJob (source video)
     │
     ▼
[analyze_clips task]  → ClipCandidates created with relevance scores
     │
     ▼
Operator reviews in /app/clipping/ dashboard:
  - Approve/reject candidates
  - Configure layout (Smart Crop / Spatial Stack / Center Crop)
  - Configure style (captions, hook, watermark, music, etc.)
  - Configure timed overlays
  - Set review gates (pause pipeline at stages 1/3/5/8 for review)
  - Generate preview image
     │
     ▼
[render_clip task]    → ClipRender with 10-stage pipeline
     │ (may pause at gate)
     ▼
Operator reviews render stages at /app/clipping/renders/<id>/
  - Can re-run from any stage
  - Can resume after gate pause
```

**Key models:**
- `ClipCandidate` — a proposed clip with layout/style config + `render_gates: list[int]`
- `ClipLayoutConfig` — render mode, crop coords, spatial stack regions (auto-created via signal)
- `ClipStyleConfig` — all visual style fields (auto-created via signal)
- `ClipTimedOverlay` — timed text overlays
- `ClipRender` — one render attempt; statuses include `PAUSED_AT_GATE`
- `ClipRenderStageResult` — per-stage result for the 10-stage pipeline

**Pipeline gate mechanism:** `render_gates` on `ClipCandidate` lists stage order numbers where the pipeline should pause. `ClipRenderPipeline.run(pause_after_stages=...)` raises `GatePausedException` at those points. The task catches it, marks the render `PAUSED_AT_GATE`, and exits cleanly (no retry).

### 4. Operator Dashboard (`/app/`)

URL namespace: `ui:` for the dashboard shell, `clipping:` for clipping views.

Key URLs:
- `/app/` — dashboard home (active jobs, recent activity)
- `/app/clipping/` — clipping job list
- `/app/clipping/<job_id>/` — job detail + candidate cards
- `/app/clipping/clips/<candidate_id>/` — candidate config (layout editor, style panels, overlays, gates)
- `/app/clipping/renders/<render_id>/` — render detail (stage list, pause/resume actions)

All views require `@staff_member_required`.

### 5. FSM State Management

**Django FSM-2 governs all pipeline state transitions.** This is non-negotiable.
- `FSMField(protected=True)` — direct assignment raises `AttributeError`
- All state changes via `@transition`-decorated methods only
- `post_transition` signals in `apps/pipeline/signals.py` fire Celery tasks
- Always use `can_proceed()` before calling a transition in non-signal code
- Never call `save()` inside a `@transition` method

**Exception:** `ClipRender.status` is a plain `CharField` (not FSM-protected) — direct assignment is safe.

### 6. Provider Abstraction

Every external API call goes through `services/providers/registry.py`. Business logic never imports API SDKs directly.

```python
# CORRECT
llm = get_llm_provider(channel=channel)
response = llm.complete(prompt=..., system=...)

# WRONG — never in pipeline/task/model code
import anthropic
client = anthropic.Anthropic(api_key=...)
```

---

## PART III: CODING STANDARDS — NON-NEGOTIABLE

### Type Annotations — Always, Everywhere

Every function signature must have complete type annotations.

```python
# CORRECT
def merge_segments(files: list[dict[str, Any]], output_path: str) -> dict[str, Any]:

# WRONG
def merge_segments(files, output_path):
```

- Use `from __future__ import annotations` at the top of every file
- Prefer `X | None` over `Optional[X]`
- No wildcard imports (`from module import *`)

### Models — Best Practices

Always define `__str__`, `Meta.ordering`, `verbose_name`, indexes.

Use `update_fields` on every `.save()` call when updating specific fields:
```python
# CORRECT
self.save(update_fields=["status", "completed_at", "updated_at"])

# WRONG
self.save()
```

Use `select_related` / `prefetch_related` explicitly — never allow N+1.

### Service Layer — Keep Models Thin

Models contain: fields, FSM transitions, simple `@property`, `__str__`, `Meta`.
Business logic goes in `services/` or `apps/<app>/services.py`.

### Error Handling — Be Specific

Never swallow exceptions silently. Never catch bare `Exception` without logging and re-raising.

### Logging — Structured and Contextual

Use structured logging with `extra={}` dicts. Never use `print()`.

```python
logger = logging.getLogger("reelforge.clipping")

logger.info(
    "Render paused at gate",
    extra={"render_id": str(render_id), "stage_order": stage_order},
)
```

### Celery Tasks

- Always `bind=True`, always set `max_retries`
- Exponential backoff: `countdown=2 ** self.request.retries * 60`
- Tasks must be idempotent
- Never dispatch tasks from inside `@transition` methods (use `post_transition` signals)

### FSM — Usage Rules

```python
# CORRECT
if can_proceed(job.retry):
    job.retry()
    job.save()  # save() is OUTSIDE the transition

# WRONG — save() inside transition, or side effects inside transition
@transition(...)
def start(self) -> None:
    self.save()              # Wrong
    send_notification(...)   # Wrong
    task.delay(...)          # Wrong
```

---

## PART IV: WHAT NOT TO DO

- **Never** import an API SDK directly in pipeline/task/model code — use the provider registry
- **Never** do `obj.status = "RUNNING"` on FSM-protected fields — use transition methods
- **Never** dispatch Celery tasks from inside `@transition` methods
- **Never** call `save()` inside a `@transition` method
- **Never** use `print()` anywhere in application code
- **Never** write a migration without a descriptive name
- **Never** store credentials or secrets unencrypted — use Fernet encryption
- **Never** write business logic in model methods
- **Never** let a rendering Celery task run without a `time_limit`
- **Never** use wildcard imports
- **Never** write a function without type annotations
- **Never** delete or update a `PipelineEvent` record (immutable audit log)
- **Never** catch `Exception` without logging and re-raising
- **Never** commit `.env` files or secret values to git

---

## PART V: ADMIN STANDARDS (Unfold)

- Every `ModelAdmin` uses `unfold.admin.ModelAdmin` as base — never plain `django.contrib.admin.ModelAdmin`
- Every list view shows status with a color-coded badge using `@display(label={...})`
- FSM models always show `available_transitions` as a display column
- Pipeline stage models always show `duration_seconds` and `agent_cost_usd` in list view
- `PipelineEvent` is always shown as a read-only `TabularInline` on `PipelineRunAdmin`
- Admin actions that trigger FSM transitions must use `can_proceed()` first

---

*Project: Reelforge — YouTube Automation HQ*
*Stack: Django 5.2 · Celery · PostgreSQL · Redis · OpenAI Agents SDK · Unfold Admin · HTMX · Alpine.js · Tailwind v4*
*Owner: Emmanuel / 29signals*
