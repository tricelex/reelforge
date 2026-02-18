# Reelforge Operator UAT Guide

> **Audience:** Operators running UAT or managing production channels.
> **Purpose:** End-to-end reference from system setup through monitoring and failure recovery.

---

## Chapter 1: System Setup & Prerequisites

### Required Services

Start all services via Docker Compose:

```bash
just build   # Build Docker images (first time only)
just up      # Start all containers in background
```

| Service | Port | Purpose |
|---------|------|---------|
| `django` | 8000 | Main Django app + Admin |
| `***REMOVED***` | 5432 | PostgreSQL database |
| `redis` | 6379 | Cache + Celery broker |
| `celeryworker` | — | Celery worker (all queues) |
| `celerybeat` | — | Scheduled task scheduler |
| `flower` | 5555 | Celery monitoring dashboard |
| `mailpit` | 8025 | Email testing (local only) |

### Required Environment Variables

Set in `.envs/.local/.django` for local development:

```bash
# Core
SECRET_KEY=<generate-with-uv-run-python-manage.py-shell>
DATABASE_URL=***REMOVED***://debug:debug@***REMOVED***:5432/***REMOVED***
REDIS_URL=redis://redis:6379/0
USE_DOCKER=yes

# AI Providers (required for pipeline to run)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
DEFAULT_LLM_PROVIDER=claude        # claude | openai | gemini

# TTS (required for voiceover generation)
ELEVENLABS_API_KEY=...
DEFAULT_TTS_PROVIDER=elevenlabs    # elevenlabs | openai_tts

# Image generation (required for B-roll + thumbnails)
FAL_API_KEY=...
DEFAULT_IMAGE_PROVIDER=fal_ai      # fal_ai | replicate | dalle
```

Optional (for full distribution pipeline):

```bash
# YouTube OAuth
YOUTUBE_OAUTH_CLIENT_CONFIG={"web":{"client_id":"...","client_secret":"...",...}}
CREDENTIAL_ENCRYPTION_KEY=<fernet-key>  # generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### First-Time Setup

```bash
just build
just up
just manage createsuperuser
```

Navigate to `http://localhost:8000/admin/` and log in with your superuser credentials.

### Verifying Celery Workers

1. Open Flower at `http://localhost:5555`
2. Click **Workers** tab — expect to see one active worker
3. Click **Queues** tab — confirm these queues are present:
   - `orchestration`, `research`, `default`, `rendering`, `uploads`, `analytics`
4. All queues should show 0 consumers initially (workers pick up tasks on demand)

---

## Chapter 2: Creating & Configuring a Channel

### Step 1: Navigate to Channels

Admin → **Channels** → **Add Channel**

### Step 2: Required Fields

| Field | Example | Notes |
|-------|---------|-------|
| `name` | "Personal Finance HQ" | Display name |
| `slug` | "personal-finance-hq" | Auto-populated from name |
| `niche_category` | FINANCE | Select from dropdown |
| `target_niches` | `["personal finance", "investing"]` | Comma-separated in admin |
| `content_tone` | conversational_authoritative | |
| `video_length_min` | 8 | Minutes |
| `video_length_max` | 14 | Minutes |

### Step 3: Voice Settings

1. Set `tts_provider` to your configured provider (e.g., `elevenlabs`)
2. Set `tts_voice_id` to the provider's voice ID
3. Test via Django shell before committing:
   ```python
   from ***REMOVED***.channels.models import Channel
   from ***REMOVED***.channels.services import ChannelSetupService

   channel = Channel.objects.get(slug="personal-finance-hq")
   svc = ChannelSetupService(channel)
   result = svc.validate_voice(voice_id=channel.tts_voice_id)
   print(result)  # {"success": True, "preview_path": "...", "duration": 2.3}
   ```

### Step 4: YouTube OAuth (for distribution)

Run in Django shell:
```python
from ***REMOVED***.channels.services import ChannelSetupService
svc = ChannelSetupService(channel)
# Exchange your OAuth2 code from the Google OAuth flow
result = svc.setup_youtube_oauth(auth_code="4/...")
print(result)  # {"success": True}
# channel.youtube_channel_id will now be populated
```

### Step 5: Competitor Channels

Under the **Competitors** inline, add at least 2-3 competitor channels:
- `youtube_channel_id`: e.g., `UCxxxxxx`
- `channel_name`: display name for reference

### Step 6: Automation Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `auto_approve_scripts` | False | If True, scripts are approved after `auto_approve_delay_hrs` without human review |
| `auto_approve_assets` | False | If True, assets proceed without review |
| `auto_upload` | False | If False, pipeline pauses before upload for manual approval |
| `auto_approve_delay_hrs` | 12 | Hours before auto-approval kicks in |

For UAT: set `auto_approve_scripts=False` and `auto_upload=False` to review each stage.

### Step 7: Activate the Channel

Set `status` to **ACTIVE**. This is required for the daily batch trigger to pick up the channel.

---

## Chapter 3: Triggering the Pipeline

### Automatic (Daily Batch)

Celery Beat runs `daily_pipeline_trigger` at 6AM UTC daily. For each ACTIVE channel, it:
1. Checks topic backlog — if fewer than 3 approved topics available, creates a `ResearchJob` and dispatches it
2. Picks the best approved `TopicIdea` (highest combined trend + gap score)
3. Creates a `PipelineRun` for that topic and dispatches `run_pipeline_orchestrator`

### Manual — Step by Step

#### 1. Trigger Research

Admin → **Channels** → select your channel → **Action: "Trigger Research Job"** → Execute

This dispatches `run_research_job_for_channel` to the research queue. Monitor in Flower. When complete, **Research Jobs** will show a COMPLETED entry with new `TopicIdea` records attached.

#### 2. Review & Approve Topic Ideas

Admin → **Research** → **Topic Ideas** → find topics for your channel

Review each topic's `trend_score`, `gap_opportunity_score`, and `title_idea`. Set `approved=True` for topics you want to produce.

#### 3. Create a Pipeline Run

Admin → **Pipeline** → **Pipeline Runs** → **Add Pipeline Run**

- `channel`: select your channel
- `topic`: select an approved TopicIdea
- Save (status starts as INITIALIZING)

#### 4. Start the Pipeline

From the PipelineRun detail page → **Action: "Start Pipeline"**

This calls `run.begin_research()` and saves, which fires the `post_transition` signal, which dispatches `run_pipeline_orchestrator` to the orchestration queue.

---

## Chapter 4: How the Orchestrator Works

### Overview

The `OrchestratorAgent` is an OpenAI Agents SDK agent running inside the `run_pipeline_orchestrator` Celery task via `asyncio.run()`. It is the brain of the pipeline.

```
run_pipeline_orchestrator (Celery task)
    └── asyncio.run(run_orchestrator(...))
            └── OrchestratorAgent (max_turns=50)
                    ├── handoff → ResearchAgent
                    ├── handoff → ScriptAgent       (only if topic exists)
                    ├── handoff → AssetAgent        (only if script_job exists)
                    └── handoff → QAAgent
```

### What the Orchestrator Does

1. Calls `get_pipeline_status` to understand where the pipeline is
2. Delegates work to sub-agents via handoffs:
   - **ResearchAgent**: discovers and scores topic ideas
   - **ScriptAgent**: writes script, generates hooks, creates SEO metadata
   - **AssetAgent**: generates voiceover, images, thumbnails, music
   - **QAAgent**: evaluates script and video quality
3. After each stage, calls `evaluate_stage_output` to score the output (0–10)
4. Calls `advance_pipeline_stage` when ready to proceed
5. Calls `pause_pipeline_for_review` if human review is needed

### Decision Logic

| Score | Action |
|-------|--------|
| < 6 | Retry the stage |
| 6–7 | Log warning, advance with note |
| ≥ 8 | Advance immediately |
| max_retries reached | `pause_pipeline_for_review` |

### Safety Limits

- `max_turns=50` on `Runner.run()` — if exceeded, the Celery task fails and the PipelineRun transitions to FAILED
- All agent decisions are logged to `PipelineEvent` (immutable audit trail)

---

## Chapter 5: Celery Task Reference

| Task | Queue | What It Does | Triggers Next |
|------|-------|--------------|---------------|
| `daily_pipeline_trigger` | orchestration | Creates ResearchJobs + PipelineRuns for active channels | `run_research_job` |
| `run_pipeline_orchestrator` | orchestration | Runs OrchestratorAgent for entire pipeline | sub-agents via handoffs |
| `run_research_job` | research | Runs ResearchAgent; saves TopicIdea records | orchestrator decides |
| `run_research_job_for_channel` | research | Creates ResearchJob + dispatches `run_research_job` | `run_research_job` |
| `run_script_job` | default | Runs ScriptAgent; saves ScriptRevision | orchestrator decides |
| `run_asset_job` | default | Runs AssetAgent; saves voiceover/images/thumbnails | orchestrator decides |
| `render_video` | rendering | MoviePy/FFmpeg render (up to 2 hours) | `run_video_qa` |
| `run_video_qa` | rendering | 9 automated QA checks | `upload_video` if passed |
| `upload_video` | uploads | YouTube Data API upload + metadata | thumbnail, pinned comment, Shorts, cross-post chain |
| `set_video_thumbnail` | uploads | Upload thumbnail to YouTube (stub) | — |
| `post_pinned_comment` | uploads | Post + pin a comment (stub) | — |
| `add_to_playlist` | uploads | Add video to playlist (stub) | — |
| `upload_youtube_short` | uploads | Upload Shorts variant (stub) | — |
| `cross_post_social` | uploads | Cross-post to TikTok/Instagram/Twitter (stub) | — |
| `sync_channel_analytics` | analytics | Creates AnalyticsSnapshot at 1d/7d/30d intervals | — |
| `weekly_analytics_sync` | analytics | Dispatches `sync_channel_analytics` for all active channels | — |

**Stub tasks** (set_video_thumbnail through cross_post_social) log intent and return — real implementations come in Phase 8.

---

## Chapter 6: FSM State Reference

### PipelineRun `overall_status`

```
INITIALIZING → RESEARCHING → SCRIPTING → AWAITING_APPROVAL →
GENERATING_ASSETS → RENDERING → QA → UPLOADING → PUBLISHED

Any active state → FAILED  (on unhandled error)
Any active state → PAUSED  (on operator pause or max retries exceeded)

From PAUSED: → GENERATING_ASSETS | RENDERING | UPLOADING  (resume transitions)
From FAILED: → SCRIPTING | GENERATING_ASSETS | RENDERING | UPLOADING  (retry transitions)
```

### Stage Job `status` (ResearchJob, ScriptJob, AssetJob, ProductionJob, DistributionJob)

```
PENDING → QUEUED → RUNNING → COMPLETED

Side paths:
RUNNING/RETRYING → FAILED  (on error)
FAILED/PAUSED → RETRYING   (if retry_count < max_retries)
Any → PAUSED               (on manual pause or QA failure)
Any → REJECTED             (operator rejection)
```

### FSM Rule

**Never** directly assign status:
```python
# WRONG — raises django_fsm.TransitionNotAllowed
run.overall_status = "PAUSED"

# CORRECT — use transition methods
run.pause_pipeline(reason="QA failed twice")
run.save()
```

---

## Chapter 7: Handling Failures

### Diagnosing a Failure

1. Admin → **Pipeline Runs** → find the failed run (status badge: red FAILED)
2. Check `last_agent_decision` JSON field — contains orchestrator's reason
3. Open the **Pipeline Events** inline — full audit trail of every transition and agent decision
4. Check Flower → **Tasks** → filter by task name to see error tracebacks

### Common Failure Scenarios

#### Script Generation Failed

1. Admin → **Scripts** → **Script Jobs** → find the failed job
2. Review `last_error` field
3. Options:
   - Manually edit `script_text` in the admin
   - Set `approved=True` on the ScriptJob
   - From the PipelineRun, use **Action: "Approve & Continue to Assets"**

#### Render Failed

1. Admin → **Production** → **Production Jobs** → find the failed job
2. Check `last_error` and `error_trace` fields
3. Fix the source asset issue (e.g., replace corrupted audio file)
4. From the PipelineRun, use **Action: "Retry Rendering"**

#### QA Failed

1. Admin → **Production** → **Production Jobs** → check `qa_results` JSON field
2. Each key in the dict is a check name; `False` = failed
3. Options:
   - Fix the issue and use "Retry Rendering"
   - If QA is overly strict, force-advance via shell:
     ```python
     from ***REMOVED***.pipeline.models import PipelineRun
     run = PipelineRun.objects.get(id="...")
     run.begin_upload()
     run.save()
     ```

#### max_turns=50 Exceeded

The orchestrator hit its safety limit. The run will be marked FAILED.

1. Inspect `PipelineEvent` records to see where it stopped
2. Fix the underlying issue (bad LLM response, infinite retry loop, etc.)
3. Use **Action: "Start Pipeline"** from the PipelineRun to restart the orchestrator from the current stage

#### max_retries Exceeded (Stage Job)

```python
# Reset retry count in shell, then retry from admin
from ***REMOVED***.scripts.models import ScriptJob
job = ScriptJob.objects.get(id="...")
job.retry_count = 0
job.save(update_fields=["retry_count", "updated_at"])
```

Then use the retry admin action.

---

## Chapter 8: Admin Actions Reference

| Location | Action | What It Does |
|----------|--------|--------------|
| Channels | **Trigger Research Job** | Creates ResearchJob + dispatches `run_research_job_for_channel` |
| Channels | **Sync Analytics Now** | Dispatches `sync_channel_analytics` for selected channels |
| Pipeline Runs | **Start Pipeline** | Calls `begin_research()` → dispatches orchestrator |
| Pipeline Runs | **Approve & Continue to Assets** | AWAITING_APPROVAL → GENERATING_ASSETS (calls `begin_assets()`) |
| Pipeline Runs | **Retry Rendering** | FAILED → RENDERING (calls `retry_rendering()`) |
| Pipeline Runs | **Pause Pipeline** | Any state → PAUSED |
| Pipeline Runs | **Reject & Archive** | → FAILED with "Rejected by operator" reason |
| Topic Ideas | **Approve Topic** | Sets `approved=True`, records approver |

---

## Chapter 9: Monitoring

### Flower Dashboard (port 5555)

- **Workers tab**: Active workers, tasks processed, task rate
- **Tasks tab**: All task executions with status, args, traceback on failure
  - Filter by task name (e.g., `***REMOVED***.pipeline.tasks.render_video`)
  - Rendering tasks should complete in under 2 hours — flag anything longer
- **Queues tab**: Queue depths. `rendering` queue should rarely have backlog.

### Pipeline Runs List View

The admin list view shows:
- Status badge (color-coded)
- Current stage
- Total cost (`total_cost_usd = agent_cost + asset_cost`)
- YouTube link (once published)
- Duration

### Pipeline Events Inline

Every PipelineRun detail page shows the `PipelineEvent` inline — this is the **immutable audit log**. Every FSM transition, agent decision, and operator action is recorded here. Never delete these records.

### Logs

Configure log aggregation to capture these loggers:

| Logger | What It Captures |
|--------|-----------------|
| `***REMOVED***.pipeline` | FSM transitions, service calls |
| `***REMOVED***.agents` | All agent activity |
| `***REMOVED***.agents.orchestrator` | Orchestrator decisions |
| `***REMOVED***.providers.llm` | LLM API calls + cost |
| `***REMOVED***.providers.tts` | TTS generation |
| `***REMOVED***.media.video` | Video rendering progress |
| `***REMOVED***.media.audio` | Audio processing |
| `***REMOVED***.youtube` | YouTube API interactions |

### Cost Tracking

- Per-run cost: `PipelineRun.total_cost_usd` (property: `total_agent_cost_usd + total_asset_cost_usd`)
- Per-stage cost: Each stage job has `agent_cost_usd`
- Per-asset cost: `AssetJob.voiceover_cost_usd`, `images_cost_usd`, `total_cost_usd`

Monitor per-channel monthly spend by summing `PipelineRun.total_agent_cost_usd + total_asset_cost_usd` for completed runs in the period.

---

## Appendix: Quick Shell Reference

```python
# --- Check pipeline run status ---
from ***REMOVED***.pipeline.models import PipelineRun
run = PipelineRun.objects.select_related("channel", "topic", "script_job").latest("created_at")
print(f"Status: {run.overall_status} | Stage: {run.current_stage}")
print(f"Cost: ${run.total_cost_usd:.4f}")

# --- List all events for a run ---
for event in run.events.order_by("created_at"):
    print(f"[{event.event_type}] {event.event_name}: {event.message}")

# --- Manually approve script and advance ---
from django_fsm import can_proceed
from ***REMOVED***.pipeline.services import PipelineService
PipelineService.approve_script_and_advance(run)

# --- Retry a failed render ---
from django_fsm import can_proceed
if can_proceed(run.retry_rendering):
    run.retry_rendering()
    run.save()

# --- Check Celery queue depth (requires Redis connection) ---
from celery import current_app
inspect = current_app.control.inspect()
print(inspect.active_queues())
```

---

*Reelforge — YouTube Automation HQ*
*Stack: Django 5.2 · Celery · PostgreSQL · Redis · OpenAI Agents SDK · Unfold Admin*
