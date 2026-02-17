# CLAUDE.md — Reelforge Project Memory

> This file is the authoritative reference for Claude Code when working on this project.
> Read this fully before writing any code. Every decision made here was deliberate.

---

## IMPLEMENTATION STATUS

**Current State**: ✅ **Infrastructure Phase Complete**

Reelforge is currently a fresh cookiecutter-django 5.2 installation with core infrastructure in place. The architecture described in Part II represents the complete vision we are building toward.

**What Works Today:**
- Django 5.2 with Django REST Framework
- PostgreSQL database
- Redis caching and Celery broker
- Celery workers and beat scheduler
- Docker Compose development environment
- Pre-commit hooks with Ruff, djlint, mypy
- Custom User model (django-allauth)
- Unfold admin theme

**What's Planned:**
- Multi-channel YouTube automation pipeline
- FSM-based orchestration
- OpenAI Agents SDK integration
- Provider abstraction layer
- Asset generation (TTS, images, music)
- Video rendering and QA
- YouTube distribution
- Analytics feedback loop

---

# PART I: CURRENT STATE & QUICK START

This section describes what exists today and how to work with the current codebase.

## 1. Project Overview

ReelForge is a multi-channel YouTube automation SaaS built with Django 5.2. The project is based on cookiecutter-django and uses Python 3.13 with `uv` for dependency management.

**Current Tech Stack:**
- Django 5.2 with Django REST Framework
- PostgreSQL (via psycopg3)
- Redis for caching and Celery broker
- Celery for async task processing
- Docker for containerization
- DRF Spectacular for API documentation
- Unfold for Django admin theme

## 2. Development Commands

### Local Development (without Docker)

Run commands with `uv run` prefix:

```bash
# Run development server
uv run python manage.py runserver

# Run tests
uv run pytest
uv run pytest path/to/test_file.py::test_name  # Run single test

# Type checking
uv run mypy reelforge

# Test coverage
uv run coverage run -m pytest
uv run coverage html
uv run open htmlcov/index.html

# Create superuser
uv run python manage.py createsuperuser

# Run Celery worker
uv run celery -A config.celery_app worker -l info

# Run Celery beat scheduler
uv run celery -A config.celery_app beat

# Django management commands
uv run python manage.py makemigrations
uv run python manage.py migrate
```

### Docker Development

Uses `just` task runner (see `justfile`):

```bash
just build              # Build Docker images
just up                 # Start all containers
just down               # Stop containers
just prune              # Remove containers and volumes
just logs [service]     # View logs
just manage [command]   # Run Django management commands
```

**Docker Services (Currently Available):**
- `django` - Main Django app (port 8000)
- `postgres` - PostgreSQL database
- `redis` - Redis cache/broker
- `celeryworker` - Celery worker
- `celerybeat` - Celery beat scheduler
- `flower` - Celery monitoring (port 5555)
- `mailpit` - Email testing (port 8025)

Environment files are in `.envs/.local/` for local development and `.envs/.production/` for production.

### Code Quality

Pre-commit hooks are configured (`.pre-commit-config.yaml`):

```bash
# Install pre-commit hooks
uv run pre-commit install

# Run manually
uv run pre-commit run --all-files
```

**Tools (Already Configured):**
- `ruff` - Linting and formatting (replaces flake8, isort, black)
- `djlint` - Django template linting and formatting
- `mypy` - Type checking
- `django-upgrade` - Auto-upgrade Django patterns to 5.2

## 3. Current Project Structure

```
reelforge/
├── config/                    # Django project configuration
│   ├── settings/
│   │   ├── base.py           # Base settings
│   │   ├── local.py          # Local development settings
│   │   ├── production.py     # Production settings
│   │   └── test.py           # Test settings
│   ├── urls.py               # Root URL configuration
│   ├── api_router.py         # DRF router configuration
│   ├── celery_app.py         # Celery configuration
│   └── wsgi.py               # WSGI application
├── reelforge/                 # Main Django app directory
│   ├── users/                # User management (cookiecutter default)
│   │   ├── models.py         # Custom User model
│   │   ├── api/              # DRF API endpoints
│   │   ├── tests/            # User tests
│   │   └── ...
│   ├── contrib/              # Third-party app customizations
│   ├── static/               # Static files
│   └── templates/            # Django templates
├── tests/                     # Project-level tests
├── compose/                   # Docker configuration files
├── .envs/                     # Environment variables (gitignored)
└── docs/                      # Sphinx documentation
```

## 4. Current Architecture Patterns

### Settings Structure

Settings are split by environment:
- `config/settings/base.py` - Common settings
- `config/settings/local.py` - Local development (uses DEBUG=True)
- `config/settings/production.py` - Production (uses environment variables)
- `config/settings/test.py` - Testing configuration

The active settings module is controlled by `DJANGO_SETTINGS_MODULE` environment variable.

### User Model

The project uses a custom User model (`reelforge.users.models.User`) extending `AbstractUser`. Always reference the User model via:
```python
from django.contrib.auth import get_user_model
User = get_user_model()
```
Or in models:
```python
from django.conf import settings
# Use settings.AUTH_USER_MODEL for ForeignKey references
```

### API Structure

DRF APIs follow this pattern:
- Viewsets in `app/api/views.py`
- Serializers in `app/api/serializers.py`
- URL registration in `config/api_router.py`
- API documentation via drf-spectacular at `/api/schema/`

### Celery Tasks

Celery is configured in `config/celery_app.py`. Create tasks in `app/tasks.py`:
```python
from config.celery_app import app

@app.task()
def my_task():
    pass
```

### Static Files & Media

- Static files: Managed by WhiteNoise in production
- Media files: Configured for Google Cloud Storage via django-storages
- Local development serves media from local filesystem

### Testing

- Uses pytest with pytest-django
- Test settings in `config/settings/test.py`
- Factory Boy for test fixtures
- Tests use `--reuse-db` flag for speed
- Coverage plugin for Django template coverage

## 5. Current Environment Variables

These are currently in use:

```bash
# Core
DJANGO_SETTINGS_MODULE=config.settings.local
SECRET_KEY=
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0

# Database
DATABASE_URL=postgres://debug:debug@localhost:5432/reelforge

# Redis / Celery
REDIS_URL=redis://localhost:6379/0

# Email (Development)
MAILGUN_API_KEY=
MAILGUN_DOMAIN=

# Storage
USE_DOCKER=yes
```

## 6. Important Notes

- **Python Version:** Requires exactly Python 3.13
- **Dependency Management:** Uses `uv` (not pip/poetry/pipenv)
- **Django Version:** 5.2 - use django-upgrade patterns
- **Database:** PostgreSQL only (no SQLite support in production)
- **Authentication:** django-allauth with MFA support
- **Email Backend:** Anymail with Mailgun in production, console in development
- **Error Tracking:** Sentry configured for production
- **CORS:** django-cors-headers configured for API access

## 7. Ruff Configuration

Ruff is configured with extensive rule sets in `pyproject.toml`. Key notes:
- Uses single-line imports (`force-single-line = true`)
- Excludes migrations automatically
- S101 (assert) ignored for tests
- Max line length follows Django conventions

## 8. Docker Compose Files

- `docker-compose.local.yml` - Local development
- `docker-compose.production.yml` - Production deployment
- `docker-compose.docs.yml` - Documentation building

Environment variable is `COMPOSE_FILE=docker-compose.local.yml` by default.

---

# PART II: ARCHITECTURE VISION

This section describes the complete Reelforge system we are building. Sections marked **[PLANNED]** represent future functionality. Sections marked **[ACTIVE]** should be applied to all code written today.

## 1. WHAT WE ARE BUILDING [PLANNED]

**Reelforge** is a multi-channel YouTube automation SaaS — a production HQ that manages the full lifecycle of faceless YouTube content from research to analytics, for multiple channels simultaneously.

### The Problem We Solve

Running a successful faceless YouTube channel requires 6-8 hours of daily work: finding topics, writing scripts, generating voiceovers, editing videos, optimizing SEO, uploading, and tracking performance. Reelforge reduces this to a monitoring task. The operator sets up a channel once and the system does everything else.

### The Product

A Django-based SaaS with:
- A pipeline that automatically researches, scripts, produces, and uploads videos
- Full operator control via Django Admin (Unfold theme) — no custom frontend required
- Multi-channel support — each channel is isolated with its own config, voice, niche, and credentials
- An AI agent system (OpenAI Agents SDK) that makes intelligent content decisions
- Celery-powered async processing with dedicated queues per stage type
- Django FSM-2 enforcing valid pipeline state transitions
- A swappable provider architecture — change LLM, TTS, or image APIs without touching pipeline code

### Who Uses It

1. **Internal use** — running Reelforge's own portfolio of channels
2. **Agency clients (29signals)** — white-labelled per client, managed from one HQ
3. **Eventually SaaS** — multi-tenant with Stripe billing

---

## 2. PLANNED ARCHITECTURE OVERVIEW [PLANNED]

### Future Project Layout

When fully implemented, the structure will be:

```
reelforge/
├── config/
│   ├── settings/
│   │   ├── base.py          # Shared settings
│   │   ├── local.py         # Local overrides
│   │   └── production.py    # Production config
│   ├── urls.py
│   ├── celery_app.py
│   └── wsgi.py
│
├── apps/                     # [PLANNED] - To be created
│   ├── core/                # Abstract base models, shared utilities
│   ├── channels/            # Channel management, credentials, config
│   ├── research/            # Topic discovery, trend analysis
│   ├── scripts/             # Script generation, hooks, SEO metadata
│   ├── assets/              # Voiceover, images, music, thumbnails
│   ├── production/          # Video rendering and post-processing
│   ├── distribution/        # YouTube upload, scheduling, cross-posting
│   ├── analytics/           # Performance tracking, feedback loop
│   ├── agents/              # All OpenAI Agents SDK agent definitions
│   └── pipeline/            # FSM orchestration, state machine, signals
│
├── services/                # [PLANNED] - To be created
│   ├── providers/           # Swappable API provider implementations
│   │   ├── base.py          # Abstract base classes for all providers
│   │   ├── registry.py      # Provider factory
│   │   ├── llm/             # Claude, GPT-4o, Gemini implementations
│   │   ├── tts/             # ElevenLabs, OpenAI TTS, Azure TTS
│   │   ├── image_gen/       # Fal.ai, Replicate, DALL-E
│   │   └── youtube/         # YouTube Data API, Analytics API
│   └── media/
│       ├── audio.py         # pydub, librosa — audio processing
│       ├── video.py         # moviepy, ffmpeg-python — video rendering
│       └── image.py         # Pillow, opencv — image manipulation
│
├── reelforge/               # Current app directory (users/ will remain)
│   └── users/              # ✅ Existing user management
│
└── storage/                 # [PLANNED] - Media file organization
    ├── scripts/
    ├── audio/
    ├── images/
    ├── thumbnails/
    ├── renders/
    └── final/
```

### The Pipeline Flow [PLANNED]

```
Channel Config
     │
     ▼
[RESEARCHING]     ResearchAgent discovers topics via YouTube, Google Trends, Reddit
     │
     ▼
[SCRIPTING]       ScriptAgent writes full script with hooks, SEO metadata, B-roll notes
     │
     ▼
[AWAITING_APPROVAL]  Operator reviews in Unfold admin (or auto-approves after delay)
     │
     ▼
[GENERATING_ASSETS]  AssetAgent: voiceover (ElevenLabs), images (Fal.ai), music, thumbnails
     │
     ▼
[RENDERING]       VideoRenderer: MoviePy compositing + FFmpeg encode with Ken Burns + subtitles
     │
     ▼
[QA]              VideoQA: 9 automated checks (audio sync, black frames, duration, etc.)
     │
     ▼
[UPLOADING]       YouTube upload + thumbnail + chapters + pinned comment + Shorts + cross-post
     │
     ▼
[PUBLISHED]       Analytics polling at 1d / 7d / 30d → feeds back into research config
```

### FSM State Management [PLANNED]

**Django FSM-2 will govern all state transitions.** This is non-negotiable.
- `PipelineStageModel.status` uses `FSMField(protected=True)`
- `PipelineRun.overall_status` uses `FSMField(protected=True)`
- `protected=True` means direct assignment (`obj.status = "X"`) raises an exception
- All state changes happen through `@transition`-decorated methods only
- `post_transition` signals in `apps/pipeline/signals.py` fire Celery tasks automatically
- `can_proceed()` is used in admin actions and agent tools before attempting transitions

### Agent Architecture (OpenAI Agents SDK) [PLANNED]

```
OrchestratorAgent              ← Master decision-maker
    │
    ├── handoff → ResearchAgent     ← Web search, trend analysis, gap analysis
    ├── handoff → ScriptAgent       ← Research, hook generation, script writing, SEO
    ├── handoff → AssetAgent        ← TTS, image gen, music selection
    └── handoff → QAAgent           ← Script QA, video QA, quality scoring
```

The OrchestratorAgent:
- Evaluates every stage output (score 0-10) before advancing
- Decides: proceed / retry / escalate to human
- Calls `advance_pipeline_stage` tool which calls `run.advance_to()` (FSM-validated)
- Logs every decision via `PipelineEvent` (immutable audit log)
- Has a `max_turns=50` safety limit

### Provider Abstraction [PLANNED]

Every external API call will go through `services/providers/registry.py`. Business logic never imports an API SDK directly.

```python
# CORRECT — always
llm = get_llm_provider(channel=channel)
response = llm.complete(prompt=..., system=...)

# WRONG — never do this in pipeline code
import anthropic
client = anthropic.Anthropic(api_key=...)
```

Swapping providers (e.g. ElevenLabs → OpenAI TTS) is done by changing `DEFAULT_TTS_PROVIDER` in settings or `channel.tts_provider` — zero pipeline code changes.

### Celery Queue Architecture [PLANNED]

```
Queue: orchestration   → OrchestratorAgent runs, daily batch triggers
Queue: research        → Research jobs, trend scraping
Queue: default         → Script generation, asset coordination
Queue: rendering       → Video render (CPU intensive, dedicated workers)
Queue: uploads         → YouTube uploads, cross-posting
Queue: analytics       → Analytics pulls, performance analysis
```

Heavy rendering jobs are isolated so they never block the upload queue.

---

## 3. DATA MODEL HIERARCHY [PLANNED]

Every model traces back to a `Channel`. One `Channel` has many `PipelineRun`s. Each `PipelineRun` links to exactly one of each stage job.

```
Channel
 └── PipelineRun
      ├── TopicIdea           (from ResearchJob)
      ├── ScriptJob           (one per TopicIdea)
      │    └── ScriptRevision (version history)
      ├── AssetJob
      │    ├── VoiceoverSegment[]
      │    ├── GeneratedImage[]
      │    └── ThumbnailOption[]
      ├── ProductionJob
      └── DistributionJob
           └── AnalyticsSnapshot[]
```

`PipelineEvent` records every state change, agent action, and operator action for a `PipelineRun`. It is **append-only** — never update or delete events.

---

## 4. CODING STANDARDS — NON-NEGOTIABLE [ACTIVE]

**Apply these standards to ALL code written today, even infrastructure code.**

### 4.1 Type Annotations — Always, Everywhere

Every function signature must have complete type annotations. No exceptions.

```python
# CORRECT
def merge_voiceover_segments(
    self,
    segment_files: list[dict[str, Any]],
    output_path: str,
    pause_between_ms: int = 200,
) -> dict[str, Any]:

# WRONG — never write this
def merge_voiceover_segments(self, segment_files, output_path, pause=200):
```

- Use `from __future__ import annotations` at the top of every file for forward references
- Use `from typing import Any, Optional, Union` — prefer `X | None` over `Optional[X]` (Python 3.10+)
- Use `TypedDict` for complex dict shapes that recur across the codebase
- Use `dataclasses` or Pydantic models for structured return values from services

```python
# For structured returns from providers
from dataclasses import dataclass

@dataclass
class LLMResponse:
    text: str
    model: str
    tokens_input: int
    tokens_output: int
    cost_usd: float
```

### 4.2 Imports — Ordered and Explicit

Always group imports in this order with a blank line between each group:

```python
# 1. Standard library
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

# 2. Django
from django.conf import settings
from django.db import models
from django.utils import timezone

# 3. Third-party
from django_fsm import FSMField, transition
from celery import shared_task

# 4. Internal — absolute imports only, never relative
from apps.channels.models import Channel
from services.providers.registry import get_llm_provider
```

Never use wildcard imports (`from module import *`). Never use implicit relative imports.

### 4.3 Naming Conventions

| Thing | Convention | Example |
|---|---|---|
| Models | PascalCase | `ScriptJob`, `AnalyticsSnapshot` |
| Model fields | snake_case | `estimated_duration_mins` |
| Services/functions | snake_case | `get_llm_provider()` |
| Constants | SCREAMING_SNAKE | `YOUTUBE_TARGET_LUFS` |
| Agent names | PascalCase string | `"OrchestratorAgent"` |
| Celery tasks | snake_case verb | `render_video`, `run_script_job` |
| URL names | kebab-case | `pipeline-run-detail` |
| Template names | snake_case | `pipeline_run_detail.html` |

Model field names should be self-documenting. Never abbreviate unless universally known (`id`, `url`, `ctr`).

```python
# CORRECT
estimated_search_volume: int
voiceover_duration_seconds: float
youtube_video_id: str

# WRONG
est_sv: int
vo_dur: float
yt_vid_id: str
```

### 4.4 Models — Best Practices

Always define `__str__`, `Meta.ordering`, and meaningful `verbose_name`/`verbose_name_plural`.

```python
class ScriptJob(PipelineStageModel):

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Script Job"
        verbose_name_plural = "Script Jobs"
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["topic"]),
        ]

    def __str__(self) -> str:
        title = self.final_title or self.topic.title_idea
        return f"Script: {title[:60]}"
```

Use `update_fields` on `.save()` whenever you're only updating specific fields:
```python
# CORRECT — only hits those columns
self.save(update_fields=["status", "completed_at", "updated_at"])

# WRONG — writes every column
self.save()
```

Use `select_related` and `prefetch_related` explicitly — never let N+1 queries happen:
```python
# In views/admin querysets
ScriptJob.objects.select_related(
    "topic__channel",
    "topic__research_job",
).prefetch_related("revisions")
```

### 4.5 Service Layer — Keep Models Thin

Models should contain:
- Field definitions
- FSM transition methods
- Simple computed properties (`@property`)
- `__str__`, `Meta`

Models should NOT contain:
- Business logic
- API calls
- File I/O
- Celery task dispatch (that's for signals)

Business logic goes in `services/` or `apps/<app>/services.py`.

```python
# CORRECT — model is thin
class AssetJob(PipelineStageModel):
    @property
    def total_images_count(self) -> int:
        return self.images.count()

# CORRECT — logic is in service
class AssetGenerationService:
    def __init__(self, asset_job: AssetJob, channel: Channel) -> None:
        self.job = asset_job
        self.channel = channel

    def generate_all(self) -> None:
        self._generate_voiceover()
        self._generate_images()
        self._generate_thumbnails()
        self._select_music()

# WRONG — logic in model
class AssetJob(PipelineStageModel):
    def generate_voiceover(self):
        import requests
        requests.post("https://api.elevenlabs.io/...")  # Never in a model
```

### 4.6 Error Handling — Be Specific

Never swallow exceptions silently. Never catch bare `Exception` unless you log and re-raise.

```python
# CORRECT
from django_fsm import TransitionNotAllowed

try:
    pipeline_run.begin_assets()
    pipeline_run.save()
except TransitionNotAllowed as exc:
    logger.error(
        "Invalid FSM transition attempted",
        extra={
            "pipeline_run_id": str(pipeline_run.id),
            "current_status": pipeline_run.overall_status,
            "attempted_transition": "begin_assets",
            "error": str(exc),
        }
    )
    raise

# CORRECT — Celery tasks
@shared_task(bind=True, max_retries=3)
def render_video(self, production_job_id: str) -> None:
    try:
        job = ProductionJob.objects.get(id=production_job_id)
        renderer = VideoRenderer(job)
        renderer.render()
    except ProductionJob.DoesNotExist:
        # Don't retry — the record is gone
        logger.error(f"ProductionJob {production_job_id} not found — aborting task")
        return
    except RenderError as exc:
        job.mark_failed(error=str(exc), trace=traceback.format_exc())
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 60)
    except Exception as exc:
        logger.critical(f"Unexpected render error: {exc}", exc_info=True)
        job.mark_failed(error=str(exc), trace=traceback.format_exc())
        raise

# WRONG
try:
    something()
except:
    pass
```

### 4.7 Logging — Structured and Contextual

Use structured logging with `extra` dicts. Never use `print()` in application code.

```python
import logging

logger = logging.getLogger("reelforge.pipeline")  # Use module-specific loggers

# CORRECT
logger.info(
    "Script generation completed",
    extra={
        "script_job_id": str(script_job.id),
        "channel_slug": script_job.topic.channel.slug,
        "word_count": script_job.word_count,
        "hook_score": script_job.hook_score,
        "cost_usd": float(script_job.agent_cost_usd),
    }
)

# WRONG
print(f"Script done: {script_job.id}")
logger.info("done")
```

Logger hierarchy:
```
reelforge                      # Root
reelforge.pipeline             # Pipeline orchestration
reelforge.agents               # All agent activity
reelforge.agents.orchestrator  # Orchestrator specifically
reelforge.media.video          # Video rendering
reelforge.media.audio          # Audio processing
reelforge.providers.llm        # LLM API calls
reelforge.providers.tts        # TTS API calls
reelforge.youtube              # YouTube API
```

### 4.8 Django Settings

Always use `django-environ` for environment variables. Never hardcode secrets. Never use `os.environ.get()` directly in settings — use `env()`.

```python
# config/settings/base.py
import environ

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

# CORRECT
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
DATABASE_URL = env.db("DATABASE_URL")
DEBUG = env.bool("DEBUG", default=False)

# WRONG
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DEBUG = True
```

All secrets rotate via environment variables. The provider registry reads from settings — changing a provider is a deploy config change, not a code change.

### 4.9 Database Migrations

- Every migration file must have a descriptive name: `0003_add_hook_score_to_scriptjob.py`
- Never edit a migration that has been applied in production — create a new one
- Add `db_index=True` on any field used in `filter()`, `order_by()`, or `get()`
- Use `django.contrib.postgres.fields.ArrayField` for lists — never store comma-separated strings
- `JSONField` is fine for unstructured/variable data but avoid it for data you'll query on

```python
# CORRECT — queryable fields use proper types
tags = ArrayField(models.CharField(max_length=100), default=list)

# WRONG — never do this
tags = models.TextField(default="")  # "tag1,tag2,tag3"
```

### 4.10 Celery Tasks [PLANNED - Apply when implementing]

- Always use `bind=True` so the task has access to `self.request.id` and retry logic
- Always set `max_retries` and `default_retry_delay`
- Always use exponential backoff on retry: `countdown=2 ** self.request.retries * 60`
- Use `task_id` from `self.request.id` and store it on the model for traceability
- Tasks should be idempotent — safe to run twice if something goes wrong

```python
@shared_task(
    bind=True,
    name="reelforge.pipeline.render_video",  # Explicit task names
    max_retries=2,
    default_retry_delay=300,
    queue="rendering",
    time_limit=7200,
    soft_time_limit=6600,
)
def render_video(self, production_job_id: str) -> None:
    """
    Render the final video for a production job.
    Idempotent: safe to retry from any point in the render process.
    """
    job: ProductionJob = ProductionJob.objects.select_related(
        "asset_job__script_job__topic__channel"
    ).get(id=production_job_id)

    job.mark_running(task_id=self.request.id)
    ...
```

### 4.11 FSM — Usage Rules [PLANNED - Apply when implementing]

- FSM transition methods should be short — set fields, nothing else
- Side effects (task dispatch, notifications) belong in `post_transition` signals, not in transition methods
- Always use `can_proceed(instance.transition_method)` before calling a transition in non-signal code
- Never call `save()` inside a transition method — call it after the transition
- If a transition has a `conditions` parameter, the condition function must be a method on the model

```python
# CORRECT — transition method is pure state mutation
@transition(field=status, source=[FAILED, PAUSED], target=RETRYING,
            conditions=[lambda self: self.can_retry()])
def retry(self) -> None:
    self.retry_count += 1
    self.last_error = ""
    self.started_at = timezone.now()

# Calling code
if can_proceed(job.retry):
    job.retry()
    job.save()  # save() is outside the transition

# WRONG — side effects inside transition
@transition(field=status, source=PENDING, target=RUNNING)
def start(self, task_id: str = "") -> None:
    self.started_at = timezone.now()
    send_notification("job started")          # Wrong — side effect
    render_video.delay(str(self.id))          # Wrong — task dispatch
    self.save()                               # Wrong — save inside transition
```

### 4.12 Agents — Usage Rules [PLANNED - Apply when implementing]

- Agent definitions live exclusively in `apps/agents/`
- Each agent is built by a `build_<name>_agent()` factory function — never instantiate `Agent()` directly in task code
- Tool functions inside agents are closures that capture `channel` and `pipeline_run` from the factory scope — keep them short and single-purpose
- Tools that write to the database must always use `update_fields` on `.save()`
- The OrchestratorAgent is the only agent that calls `can_proceed()` and `advance_to()`
- Sub-agents (Research, Script, Asset) do not know about `PipelineRun` — they only operate on their own model
- Always pass `max_turns` to `Runner.run()` — never let an agent run unbounded

```python
# CORRECT — factory with captured context
def build_script_agent(channel: Channel, topic: TopicIdea) -> Agent:

    @Tool(name="save_script_draft")
    def save_script_draft(script_job_id: str, script_text: str) -> dict[str, Any]:
        job = ScriptJob.objects.get(id=script_job_id)
        job.script_text = script_text
        job.save(update_fields=["script_text", "updated_at"])
        return {"saved": True}

    return Agent(
        name="ScriptAgent",
        model="gpt-4o",
        instructions=f"...",
        tools=[save_script_draft]
    )

# WRONG — agent instantiated inline in a task
@shared_task
def run_script_job(script_job_id: str) -> None:
    agent = Agent(name="ScriptAgent", ...)  # Never do this
```

---

## 5. PROVIDER ABSTRACTION — HOW TO ADD A NEW PROVIDER [PLANNED]

When a new TTS provider (e.g. Azure TTS) becomes available or preferred:

1. Create `services/providers/tts/azure.py` implementing `BaseTTSProvider`
2. Add it to `_build_tts_provider()` in `services/providers/registry.py`
3. Set `DEFAULT_TTS_PROVIDER=azure` in `.env` or `channel.tts_provider = "azure"` per-channel
4. Done — zero changes to pipeline, tasks, or agents

This is the only acceptable way to switch providers. Never add provider-specific logic to pipeline code.

---

## 6. UNFOLD ADMIN — STANDARDS [ACTIVE]

The Django admin is the **entire operator interface** for Reelforge. It must be excellent.

- Every `ModelAdmin` uses `unfold.admin.ModelAdmin` as base — never `django.contrib.admin.ModelAdmin`
- Every list view must show status with a color-coded badge using `@display(label={...})`
- Every model with a `status` FSM field must show `available_transitions` as a display column
- Pipeline stage models always show `duration_seconds` and `agent_cost_usd` in list view
- `PipelineEvent` is always shown as a read-only `TabularInline` on `PipelineRunAdmin`
- File fields (audio, video, images) should show preview or playback links where possible
- Admin actions that trigger FSM transitions must use `can_proceed()` before calling the transition
- Bulk actions must handle partial failures gracefully and report per-item results

```python
# Status badge pattern — use consistently across all stage models
@display(
    description="Status",
    ordering="status",
    label={
        "PENDING":   "default",
        "RUNNING":   "info",
        "COMPLETED": "success",
        "FAILED":    "danger",
        "PAUSED":    "warning",
        "RETRYING":  "warning",
        "REJECTED":  "default",
    }
)
def status_badge(self, obj: PipelineStageModel) -> str:
    return obj.status
```

---

## 7. FILE STORAGE CONVENTIONS [PLANNED]

All file paths follow a deterministic structure keyed on model IDs:

```
storage/
├── scripts/        {script_job_id}.txt
├── audio/
│   ├── segments/   {asset_job_id}/seg_{segment_id}.mp3
│   └── full/       {asset_job_id}/voiceover.mp3
├── images/         {asset_job_id}/{position_idx}.jpg
├── thumbnails/
│   ├── options/    {asset_job_id}/thumb_{option_number}.jpg
│   └── selected/   {asset_job_id}/selected.jpg
├── renders/
│   ├── raw/        {production_job_id}_raw.mp4
│   ├── processed/  {production_job_id}_processed.mp4
│   └── shorts/     {production_job_id}_shorts.mp4
└── temp/           Cleaned up after 24 hours by a scheduled task
```

Never hardcode paths. Always derive them from model IDs using helper functions in `apps/core/storage.py`.

```python
# apps/core/storage.py
def get_voiceover_segment_path(asset_job_id: str, segment_id: int) -> Path:
    return settings.MEDIA_ROOT / "audio" / "segments" / asset_job_id / f"seg_{segment_id}.mp3"

def get_render_path(production_job_id: str, variant: str = "processed") -> Path:
    # variant: "raw" | "processed" | "shorts"
    return settings.MEDIA_ROOT / "renders" / variant / f"{production_job_id}_{variant}.mp4"
```

---

## 8. AUDIO/VIDEO PROCESSING — RULES [PLANNED]

### Audio

- All audio processing uses `pydub` for manipulation and `ffmpeg-python` for encoding/normalization
- Target loudness: **-16 LUFS integrated** (YouTube standard)
- True peak ceiling: **-1.5 dBTP**
- Export format: MP3 192kbps for segments, MP3 320kbps for final mixed audio
- Sample rate: always resample to **44100 Hz** before export
- Background music volume: calculated in **dB** relative to voiceover dBFS — never use fixed percentages

### Video

- Resolution: **1920×1080** (never lower for main video)
- Shorts: **1080×1920** (9:16 crop from center of 16:9 frame)
- Frame rate: **30fps**
- Codec: `libx264` with `crf=18` for archival quality, `preset=slow` for production
- Audio: `aac` at `192k` bitrate, `movflags=+faststart` for streaming
- Ken Burns: max zoom delta of **3%** over clip duration — subtle, never jarring
- Subtitle font: `Montserrat-Bold`, size 52, white with 3px black stroke
- `ffmpeg.probe()` before every file operation — never assume file validity

---

## 9. ENVIRONMENT VARIABLES REFERENCE

### Currently Used

```bash
# Core
DJANGO_SETTINGS_MODULE=config.settings.local
SECRET_KEY=
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0

# Database
DATABASE_URL=postgres://debug:debug@localhost:5432/reelforge

# Redis / Celery
REDIS_URL=redis://localhost:6379/0

# Email
MAILGUN_API_KEY=
MAILGUN_DOMAIN=

# Storage
USE_DOCKER=yes
```

### Planned (Production)

```bash
# Core
DJANGO_SETTINGS_MODULE=config.settings.production
SECRET_KEY=
DEBUG=False
ALLOWED_HOSTS=

# Database
DATABASE_URL=postgres://user:pass@host:5432/reelforge

# Redis / Celery
REDIS_URL=redis://localhost:6379/0

# AI Providers
ANTHROPIC_API_KEY=
OPENAI_API_KEY=

# TTS
ELEVENLABS_API_KEY=

# Image Generation
FAL_API_KEY=
REPLICATE_API_KEY=

# YouTube
YOUTUBE_OAUTH_CLIENT_CONFIG={"web":{"client_id":...}}  # JSON string

# Security
CREDENTIAL_ENCRYPTION_KEY=  # Fernet key for OAuth credential encryption

# Provider Defaults (overridable per channel)
DEFAULT_LLM_PROVIDER=claude          # claude | openai | gemini
DEFAULT_TTS_PROVIDER=elevenlabs      # elevenlabs | openai_tts | azure_tts
DEFAULT_IMAGE_PROVIDER=fal_ai        # fal_ai | replicate | dalle

# Storage
MEDIA_ROOT=/var/reelforge/storage
```

---

## 10. TECH STACK — CANONICAL VERSIONS

| Package | Version | Purpose | Status |
|---|---|---|---|
| Django | >=5.2 | Web framework | ✅ 5.2 Installed |
| Celery | >=5.3 | Async task queue | ✅ 5.4.0 Installed |
| django-unfold | >=0.40.0 | Admin UI theme | ✅ 0.45.0 Installed |
| django-fsm-2 | >=2.3.0 | Pipeline state machine | ⏳ Needed |
| django-fsm-log | >=3.0.0 | FSM audit log | ⏳ Needed |
| openai-agents | >=0.0.5 | Multi-agent orchestration | ⏳ Needed |
| anthropic | >=0.30.0 | Claude API client | ⏳ Needed |
| openai | >=1.30.0 | OpenAI API client | ⏳ Needed |
| moviepy | >=2.0.0 | Video compositing | ⏳ Needed |
| ffmpeg-python | >=0.2.0 | FFmpeg bindings | ⏳ Needed |
| pydub | >=0.25.0 | Audio manipulation | ⏳ Needed |
| librosa | >=0.10.0 | Audio analysis | ⏳ Needed |
| soundfile | >=0.12.0 | Audio file I/O | ⏳ Needed |
| Pillow | >=10.0.0 | Image processing | ✅ Installed |
| opencv-python | >=4.9.0 | Advanced image ops | ⏳ Needed |
| google-api-python-client | >=2.130.0 | YouTube Data API | ⏳ Needed |
| google-auth-oauthlib | >=1.2.0 | YouTube OAuth2 | ⏳ Needed |
| cryptography | >=42.0.0 | Credential encryption | ✅ Installed |
| django-environ | >=0.11.0 | Environment variables | ✅ Installed |
| psycopg | >=3.1.0 | PostgreSQL driver | ✅ 3.2.3 Installed |
| redis | >=5.0.0 | Redis client | ✅ 5.2.1 Installed |
| django-celery-beat | >=2.6.0 | Periodic tasks | ✅ 2.7.0 Installed |
| praw | >=7.7.0 | Reddit API | ⏳ Needed |
| pytrends | >=4.9.0 | Google Trends | ⏳ Needed |

---

## 11. WHAT NOT TO DO [ACTIVE]

These are mistakes to avoid regardless of what seems convenient in the moment:

- **Never** import an API SDK directly in pipeline, task, or model code — use the provider registry
- **Never** do `obj.status = "RUNNING"` — FSMField is `protected=True`, use transition methods
- **Never** dispatch Celery tasks from inside `@transition` methods — use `post_transition` signals
- **Never** call `save()` inside a `@transition` method
- **Never** use `print()` anywhere in application code — use `logger`
- **Never** write a migration without a descriptive name
- **Never** store credentials or secrets in the database unencrypted — use Fernet encryption
- **Never** write business logic in model methods — use service classes
- **Never** write pipeline logic in admin classes — admin calls service methods
- **Never** let a Celery task run without a `time_limit` on rendering tasks
- **Never** use wildcard imports
- **Never** write a function without type annotations
- **Never** delete or update a `PipelineEvent` record — it's an immutable audit log
- **Never** catch `Exception` without logging and re-raising

---

## 12. QUICK REFERENCE — KEY FILES [PLANNED]

When implemented, these will be the critical files:

| File | What it contains | Status |
|---|---|---|
| `apps/core/models.py` | `UUIDModel`, `TimestampedModel`, `PipelineStageModel` with FSM | ⏳ To be created |
| `apps/pipeline/models.py` | `PipelineRun` with FSM transitions, `PipelineEvent` | ⏳ To be created |
| `apps/pipeline/signals.py` | `post_transition` → Celery task dispatch (single source of truth) | ⏳ To be created |
| `apps/pipeline/services.py` | `PipelineService` — batch trigger, retry, approve logic | ⏳ To be created |
| `apps/agents/orchestrator.py` | `build_orchestrator()` factory, `run_orchestrator()` async entry point | ⏳ To be created |
| `services/providers/registry.py` | `get_llm_provider()`, `get_tts_provider()`, etc. — provider factory | ⏳ To be created |
| `services/providers/base.py` | `BaseLLMProvider`, `BaseTTSProvider`, `BaseImageProvider` ABCs | ⏳ To be created |
| `services/media/audio.py` | `AudioProcessor` — segment merge, mastering, music mix | ⏳ To be created |
| `services/media/video.py` | `VideoRenderer`, `VideoQA` — render pipeline, QA checks | ⏳ To be created |
| `apps/core/storage.py` | Path helper functions for all file types | ⏳ To be created |

---

# PART III: IMPLEMENTATION ROADMAP

This section provides a phased approach to building out the complete Reelforge architecture.

## Phase 0: Infrastructure ✅ COMPLETE

**Status**: Complete - cookiecutter-django 5.2 installation

**What's Done:**
- Django 5.2 with DRF
- PostgreSQL database
- Redis cache
- Celery workers and beat
- Docker Compose setup
- Pre-commit hooks (Ruff, mypy, djlint)
- Unfold admin theme
- Custom User model
- Testing framework (pytest)

## Phase 1: Core Models and FSM Foundation

**Goal**: Establish the data model hierarchy and FSM orchestration layer

**Dependencies to Install:**
```bash
uv add django-fsm-2
uv add django-fsm-log
```

**Apps to Create:**
1. `apps/core/` - Abstract base models
   - `UUIDModel` - UUID primary keys
   - `TimestampedModel` - created_at, updated_at
   - `PipelineStageModel` - Abstract base with FSM status field
   - `storage.py` - Path helper functions

2. `apps/channels/` - Channel management
   - `Channel` model with credentials and config
   - Admin interface for channel setup
   - Provider preference fields

3. `apps/pipeline/` - Orchestration
   - `PipelineRun` model with FSM
   - `PipelineEvent` audit log model
   - `signals.py` for post_transition handlers
   - Admin interface for monitoring runs

**Key Deliverables:**
- FSM state machine working with protected transitions
- PipelineEvent audit log capturing all state changes
- Channel CRUD in admin
- Basic PipelineRun creation and transitions

## Phase 2: Provider Registry

**Goal**: Build the swappable provider abstraction layer

**Dependencies to Install:**
```bash
uv add anthropic
uv add openai
```

**Create:**
1. `services/providers/base.py`
   - `BaseLLMProvider` ABC
   - `BaseTTSProvider` ABC (stub for now)
   - `BaseImageProvider` ABC (stub for now)

2. `services/providers/registry.py`
   - `get_llm_provider()` factory
   - Environment variable + channel override logic

3. `services/providers/llm/`
   - `claude.py` - Anthropic implementation
   - `openai_llm.py` - OpenAI implementation

**Key Deliverables:**
- Can swap LLM provider via environment variable
- Can override provider per channel
- All provider calls return standardized dataclass results
- Cost tracking built into every provider call

## Phase 3: Research Pipeline (First Complete Stage)

**Goal**: Build the first end-to-end pipeline stage

**Dependencies to Install:**
```bash
uv add praw
uv add pytrends
```

**Create:**
1. `apps/research/`
   - `ResearchJob` model
   - `TopicIdea` model
   - `services.py` - Research orchestration
   - `tasks.py` - Celery tasks
   - Admin interface

2. Test the complete flow:
   - Create Channel → Create PipelineRun → Trigger Research
   - FSM transitions work
   - PipelineEvent logging works
   - Celery tasks dispatch correctly

**Key Deliverables:**
- First working pipeline stage
- Integration with YouTube Data API
- Trend analysis from Google Trends
- Topic scoring and ranking
- Admin review interface

## Phase 4: OpenAI Agents Integration

**Goal**: Add the agent system for intelligent decision-making

**Dependencies to Install:**
```bash
uv add openai-agents
```

**Create:**
1. `apps/agents/`
   - `orchestrator.py` - OrchestratorAgent factory
   - `research.py` - ResearchAgent factory
   - `base.py` - Shared agent utilities

2. Integrate with Research stage:
   - ResearchAgent evaluates topics
   - OrchestratorAgent decides whether to proceed
   - Tool functions for FSM transitions

**Key Deliverables:**
- OrchestratorAgent can evaluate stage outputs
- Agent decisions logged to PipelineEvent
- `max_turns` safety limits enforced
- Cost tracking per agent run

## Phase 5: Script Generation

**Goal**: Build the script writing stage

**Create:**
1. `apps/scripts/`
   - `ScriptJob` model
   - `ScriptRevision` model (version history)
   - `services.py` - Script generation logic
   - `tasks.py` - Celery tasks
   - Admin with revision history inline

2. `apps/agents/script.py`
   - ScriptAgent factory
   - Tools for saving drafts
   - Hook generation
   - SEO metadata

**Key Deliverables:**
- Script generation from TopicIdea
- Version history tracking
- Manual approval workflow in admin
- Hook quality scoring
- SEO metadata generation

## Phase 6: Asset Generation

**Goal**: TTS, images, music, thumbnails

**Dependencies to Install:**
```bash
uv add elevenlabs (or use openai for TTS)
uv add pydub
uv add librosa
uv add soundfile
```

**Create:**
1. `apps/assets/`
   - `AssetJob` model
   - `VoiceoverSegment` model
   - `GeneratedImage` model
   - `ThumbnailOption` model
   - `services.py` - Asset coordination

2. `services/providers/tts/`
   - `elevenlabs.py` or `openai_tts.py`

3. `services/providers/image_gen/`
   - `fal_ai.py` or `replicate.py`

4. `services/media/audio.py`
   - AudioProcessor class
   - Segment merging
   - Music mixing
   - Loudness normalization (-16 LUFS)

**Key Deliverables:**
- Voiceover generation and merging
- Background music selection and mixing
- Image generation based on script B-roll notes
- Thumbnail generation with multiple options
- File storage following conventions in section 7

## Phase 7: Video Production

**Goal**: Video rendering and QA

**Dependencies to Install:**
```bash
uv add moviepy
uv add ffmpeg-python
uv add opencv-python
```

**Create:**
1. `apps/production/`
   - `ProductionJob` model
   - `services.py` - Render coordination

2. `services/media/video.py`
   - VideoRenderer class
   - Ken Burns effects
   - Subtitle rendering
   - Shorts creation (9:16 crop)
   - VideoQA class with 9 automated checks

**Key Deliverables:**
- Full video rendering pipeline
- Ken Burns effects on images
- Subtitle overlays
- Shorts variant creation
- QA checks (audio sync, black frames, duration, etc.)
- Render queue isolated from other Celery tasks

## Phase 8: Distribution

**Goal**: YouTube upload and cross-posting

**Dependencies to Install:**
```bash
uv add google-api-python-client
uv add google-auth-oauthlib
uv add cryptography  # Already installed
```

**Create:**
1. `apps/distribution/`
   - `DistributionJob` model
   - `services.py` - Upload orchestration
   - OAuth credential encryption/decryption

2. `services/providers/youtube/`
   - YouTube Data API implementation
   - OAuth flow handling
   - Upload with metadata
   - Chapter markers
   - Pinned comments

**Key Deliverables:**
- YouTube OAuth credential management (encrypted)
- Video upload with full metadata
- Thumbnail upload
- Chapter markers
- Pinned comment posting
- Shorts upload
- Scheduling support

## Phase 9: Analytics and Feedback Loop

**Goal**: Performance tracking and research feedback

**Create:**
1. `apps/analytics/`
   - `AnalyticsSnapshot` model
   - `services.py` - Analytics polling
   - Feedback to research config

2. Celery beat tasks:
   - Poll at 1d, 7d, 30d intervals
   - Update Channel research preferences based on performance

**Key Deliverables:**
- Periodic analytics polling
- Performance tracking (views, CTR, watch time, etc.)
- Feedback into research topic selection
- Admin dashboards for channel performance

## Phase 10: Production Hardening

**Goal**: Make it bulletproof for production use

**Tasks:**
1. Comprehensive error handling and retry logic
2. Rate limiting for all external APIs
3. Cost monitoring and budget limits
4. Sentry integration for error tracking
5. Monitoring dashboards (Flower, custom admin views)
6. Backup and recovery procedures
7. Multi-tenant isolation (if going SaaS route)
8. Stripe billing integration (if SaaS)

## Critical Path Summary

**Minimum Viable Pipeline (Phases 1-7):**
1. Core models + FSM
2. Provider registry
3. Research stage
4. Agent system
5. Script stage
6. Asset stage
7. Production stage

**For First Real Video:**
- Need Phases 1-8 complete
- Distribution stage is required to actually publish

**For Self-Improving System:**
- Need Phase 9 (Analytics feedback)

---

## Next Steps (Start Here)

When ready to begin implementation:

1. **Install Phase 1 dependencies**:
   ```bash
   uv add django-fsm-2
   uv add django-fsm-log
   ```

2. **Create apps directory**:
   ```bash
   mkdir -p apps/core apps/channels apps/pipeline
   ```

3. **Build abstract base models in `apps/core/models.py`**:
   - UUIDModel
   - TimestampedModel
   - PipelineStageModel (with FSM)

4. **Create Channel model** in `apps/channels/models.py`

5. **Create PipelineRun and PipelineEvent** in `apps/pipeline/models.py`

6. **Set up admin interfaces** using Unfold standards from section 6

7. **Write initial migrations** with descriptive names

8. **Test FSM transitions** in Django shell or pytest

---

*Project: Reelforge — YouTube Automation HQ*
*Stack: Django 5.2 · Celery · PostgreSQL · Redis · OpenAI Agents SDK · Unfold Admin*
*Owner: Emmanuel / 29signals*
