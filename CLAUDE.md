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



## 6. Important Notes

- **Python Version:** Requires exactly Python 3.13
- **Dependency Management:** Uses `uv` (not pip/poetry/pipenv)
- **Django Version:** 5.2 - use django-upgrade patterns
- **Database:** PostgreSQL only (no SQLite support in production)
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


Never use wildcard imports (`from module import *`). Never use implicit relative imports.

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

*Project: Reelforge — YouTube Automation HQ*
*Stack: Django 5.2 · Celery · PostgreSQL · Redis · OpenAI Agents SDK · Unfold Admin*
*Owner: Emmanuel / 29signals*