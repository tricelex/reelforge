# Reelforge — Clipping Feature: Unified KRD
## For Claude Code Implementation

**Version:** 2.0 — Unified (existing implementation + new architecture)
**Date:** April 2026
**Status:** Implementation-Ready

---

## Table of Contents

1. [Purpose & Scope](#1-purpose--scope)
2. [Architectural Decisions](#2-architectural-decisions)
3. [What Exists — Inventory](#3-what-exists--inventory)
4. [What Changes — Delta from Existing](#4-what-changes--delta-from-existing)
5. [What Is New](#5-what-is-new)
6. [Domain Models](#6-domain-models)
7. [FSM — ClippingJob State Machine](#7-fsm--clippingjob-state-machine)
8. [Celery Task Architecture](#8-celery-task-architecture)
9. [Render Pipeline — All 10 Stages](#9-render-pipeline--all-10-stages)
10. [Speaker Detection — Upgraded](#10-speaker-detection--upgraded)
11. [Gate Mechanism](#11-gate-mechanism)
12. [SSE — Real-Time Status Streaming](#12-sse--real-time-status-streaming)
13. [REST API — DRF Contracts](#13-rest-api--drf-contracts)
14. [Global Asset Library](#14-global-asset-library)
15. [Frontend — Next.js Screens & Integration](#15-frontend--nextjs-screens--integration)
16. [Django Project Structure](#16-django-project-structure)
17. [Tech Stack](#17-tech-stack)
18. [Implementation Phases](#18-implementation-phases)

---

## 1. Purpose & Scope

This document is the single source of truth for building the Reelforge Clipping Feature. It synthesises:
- **The existing partial implementation** (`***REMOVED***/clipping/`) — models, tasks, render pipeline, services, signals documented in the current KRD
- **The target architecture** — Channel removed, SocialAccount as direct FK, global asset library, SSE real-time, DRF REST API, Next.js frontend, upgraded speaker detection

The backend is Django 5.x + Celery. The frontend is a **separate Next.js repo**. All existing Django template views (`views/jobs.py`, `views/candidates.py`, `views/renders.py`) and all templates are **discarded** — they are replaced entirely by DRF ViewSets.

---

## 2. Architectural Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Channel concept | **Removed** | `ClippingJob` links directly to `SocialAccount` |
| Job → SocialAccount | **1:1 FK** (one job = one account) | Simpler model, cleaner data |
| Asset/template scope | **Global** (one shared library) | Single operator, no need for per-account isolation |
| Auto-approve clips | **Removed** | Always require manual approval per candidate |
| Real-time updates | **SSE (Server-Sent Events)** | Simpler than Django Channels, sufficient for one-way push |
| Frontend | **Next.js — separate repo** | Full decoupling from Django templates |
| Speaker detection | **MediaPipe + PyAnnote** | Full upgrade from OpenCV Haar cascade |
| REST API | **Django REST Framework ViewSets** | Replaces all HTMX/template views |

---

## 3. What Exists — Inventory

The following are already implemented and **carry forward with modifications noted in Section 4**.

### Models (`***REMOVED***/clipping/models.py`)
| Model | Status |
|-------|--------|
| `ClippingJob` | ✅ Keep — modify fields (see §4) |
| `ClipCandidate` | ✅ Keep as-is |
| `ClipLayoutConfig` | ✅ Keep as-is |
| `ClipRenderTemplate` | ✅ Keep — modify scope (see §4) |
| `ClipStyleConfig` | ✅ Keep — remove channel ref in signal |
| `ClipTimedOverlay` | ✅ Keep as-is |
| `ClipRender` | ✅ Keep as-is |
| `ClipRenderStageResult` | ✅ Keep as-is |
| `ClipMediaAsset` | ✅ Keep — remove channel FK |
| `ClipMusicAsset` | ✅ Keep — remove channel FK |
| `ClipPost` | ✅ Keep as-is |

### Celery Tasks (`***REMOVED***/clipping/tasks.py`)
| Task | Status |
|------|--------|
| `download_source_video` | ✅ Keep as-is |
| `transcribe_video` | ✅ Keep as-is |
| `analyze_clips` | ✅ Keep — remove auto-approve logic |
| `render_clip` | ✅ Keep as-is |
| `preview_clip_layout` | ✅ Keep as-is |
| `preview_clip_style` | ✅ Keep as-is |
| `post_clip` | ✅ Keep as-is |
| `sync_clip_analytics` | ✅ Keep as-is |

### Render Pipeline (`***REMOVED***/services/media/`)
| Component | Status |
|-----------|--------|
| `ClipRenderPipeline` | ✅ Keep as-is |
| `PipelineRenderConfig` | ✅ Keep as-is |
| `GatePausedException` | ✅ Keep as-is |
| Stage 1 — `TrimAndCropStage` | ✅ Keep — upgrade speaker detection (§10) |
| Stage 2 — `IntroConcatStage` | ✅ Keep as-is |
| Stage 3 — `HookStage` | ✅ Keep as-is |
| Stage 4 — `CaptionTranslationStage` | ✅ Keep as-is |
| Stage 5 — `CaptionStage` | ✅ Keep as-is |
| Stage 6 — `WatermarkStage` | ✅ Keep as-is |
| Stage 7 — `TimedOverlayStage` | ✅ Keep as-is |
| Stage 8 — `ProgressBarStage` | ✅ Keep as-is |
| Stage 9 — `OutroConcatStage` | ✅ Keep as-is |
| Stage 10 — `MusicMixStage` | ✅ Keep as-is |

### Services
| Service | Status |
|---------|--------|
| `ClipAnalysisService` | ✅ Keep — remove channel niche_category ref |
| `SpeakerDetectionService` (OpenCV) | 🔄 Replace with MediaPipe + PyAnnote (§10) |

### What is Discarded Entirely
- All files in `***REMOVED***/clipping/views/` (`jobs.py`, `candidates.py`, `renders.py`)
- All Django templates in `***REMOVED***/templates/clipping/`
- `***REMOVED***/clipping/urls.py` — replaced with DRF router
- Signal: `create_clip_render_template_for_channel`
- `auto_approve_clips` field and all auto-approve logic

---

## 4. What Changes — Delta from Existing

### 4.1 `ClippingJob` Model

**Remove:**
- `channel` — FK to Channel (entire field removed)
- `target_accounts` — M2M to SocialAccount (replaced by 1:1 FK)

**Add:**
- `social_account` — `ForeignKey(SocialAccount, on_delete=PROTECT, related_name="clipping_jobs")`

**Result:** One job produces clips for exactly one social account. The social account tells the system which platform this is for (TikTok, YouTube, Instagram), which informs format defaults.

### 4.2 `ClipRenderTemplate` Model

**Remove:**
- `channel` — `OneToOneField(Channel)` removed

**Add:**
- `name` — `CharField(max_length=100, default="Default Template")` — allows multiple named templates
- `is_default` — `BooleanField(default=False)` — one can be marked as the system default

**Result:** Global style templates, no channel association. The operator can have multiple named templates and pick one per job. If none chosen, the `is_default=True` template is used.

### 4.3 `ClipMediaAsset` Model

**Remove:**
- `channel` — FK to Channel removed

**Result:** Global intro/outro library shared across all jobs.

### 4.4 `ClipMusicAsset` Model

**Remove:**
- `channel` — FK to Channel removed

**Result:** Global music library shared across all jobs.

### 4.5 `ClipStyleConfig` Model

**Add:**
- `render_template` — `ForeignKey(ClipRenderTemplate, null=True, blank=True, on_delete=SET_NULL)` — tracks which template was used to seed this config

### 4.6 Signals (`***REMOVED***/clipping/signals.py`)

**Remove entirely:**
- `create_clip_render_template_for_channel` — no longer needed

**Modify: `create_layout_config_for_candidate`**

Before:
```python
render_mode = candidate.clipping_job.channel.default_render_mode
layout_defaults = candidate.clipping_job.channel.default_layout_config
```

After:
```python
# Use social account platform to pick default render mode
account = candidate.clipping_job.social_account
platform = account.platform  # 'tiktok' | 'youtube' | 'instagram'
render_mode = PLATFORM_RENDER_MODE_DEFAULTS.get(platform, RenderMode.SMART_CROP)
# No channel layout defaults — start from system defaults
```

Add to `constants.py`:
```python
PLATFORM_RENDER_MODE_DEFAULTS = {
    "tiktok": RenderMode.SMART_CROP,
    "youtube": RenderMode.CENTER_CROP,
    "instagram": RenderMode.SMART_CROP,
}

PLATFORM_FORMAT_DEFAULTS = {
    "tiktok": "VERTICAL_9_16",
    "youtube": "LANDSCAPE_16_9",
    "instagram": "SQUARE_1_1",
}
```

**Modify: `create_style_config_for_candidate`**

Before:
```python
template = ClipRenderTemplate.to_style_defaults()  # via channel
```

After:
```python
template = ClipRenderTemplate.objects.filter(is_default=True).first()
if not template:
    template = ClipRenderTemplate.objects.first()  # fallback
# Proceed with existing copy logic
```

### 4.7 `analyze_clips` Task

**Remove auto-approve block entirely:**
```python
# DELETE this entire block:
all_auto = all(account.auto_approve_clips for account in job.target_accounts.all())
if all_auto:
    ...auto approve and dispatch...
```

**After analysis always:**
```python
job.await_clip_approval()
job.save(update_fields=["status"])
```

### 4.8 `ClipAnalysisService`

**Remove:**
- Any reference to `job.channel.niche_category` in prompt building

**Add to prompt context:**
```python
platform = job.social_account.platform
account_name = job.social_account.username
# Include platform in system prompt for format-specific clip suggestions
```

### 4.9 URL Configuration

**Remove:** `***REMOVED***/clipping/urls.py` (old template-based routes)

**Add:** DRF router registration in `config/urls.py` (see §13)

---

## 5. What Is New

### 5.1 DRF ViewSets + Serializers
Full REST API replacing all template views. All endpoints return JSON. See §13.

### 5.2 SSE Real-Time Endpoint
`GET /api/v1/clipping/jobs/{id}/stream/` — streams pipeline status events as Server-Sent Events. See §12.

### 5.3 Upgraded Speaker Detection
`SpeakerDetectionService` rebuilt with MediaPipe face detection + PyAnnote diarization. See §10.

### 5.4 Diarization-Enriched Analysis
`ClipAnalysisService` enhanced to include speaker diarization data alongside the transcript when calling GPT-4o, producing richer clip suggestions with speaker context.

### 5.5 Scene Detection
`PySceneDetect` integrated into the analysis task, adding scene cut timestamps to the job analysis data.

### 5.6 `analysis_manifest` JSONField on `ClippingJob`
New field to store the full structured analysis output (diarization segments, scene cuts, speaker-face mappings) separately from the raw `transcript_json`. This allows the frontend to display a rich timeline.

---

## 6. Domain Models

All models in `***REMOVED***/clipping/models.py`. All inherit `BaseAbstractModel` (UUID PK, `created_at`, `updated_at`, soft delete).

---

### 6.1 `ClippingJob`

```python
class ClippingJob(BaseAbstractModel):
    # ── Destination (replaces channel + target_accounts) ──────────────────
    social_account = models.ForeignKey(
        "accounts.SocialAccount",
        on_delete=models.PROTECT,
        related_name="clipping_jobs",
    )

    # ── Source ────────────────────────────────────────────────────────────
    source_type         = models.CharField(max_length=20)  # YOUTUBE_URL | DIRECT_URL | UPLOAD
    source_url          = models.URLField(blank=True, null=True)
    source_video_file   = models.FileField(upload_to="clipping/source/", blank=True, null=True)
    downloaded_file     = models.FileField(upload_to="clipping/downloaded/", blank=True, null=True)
    source_title        = models.CharField(max_length=500, blank=True)
    source_duration_sec = models.FloatField(null=True, blank=True)

    # ── Transcription ─────────────────────────────────────────────────────
    transcript_text          = models.TextField(blank=True)
    transcript_json          = models.JSONField(null=True, blank=True)  # Whisper word-level segments
    transcription_provider   = models.CharField(max_length=50, blank=True)
    transcription_cost_usd   = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)

    # ── Analysis ──────────────────────────────────────────────────────────
    clips_requested          = models.PositiveIntegerField(default=5)
    analysis_provider        = models.CharField(max_length=50, blank=True)
    analysis_cost_usd        = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)
    agent_run_id             = models.CharField(max_length=255, blank=True)
    agent_cost_usd           = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)

    # ── Analysis Manifest (NEW) ───────────────────────────────────────────
    # Stores structured diarization, scene cuts, speaker-face mappings, AI suggestions
    analysis_manifest        = models.JSONField(null=True, blank=True)

    # ── Derived display assets ────────────────────────────────────────────
    thumbnail_strip_file     = models.FileField(upload_to="clipping/thumbnails/", blank=True, null=True)
    waveform_data_file       = models.FileField(upload_to="clipping/waveforms/", blank=True, null=True)

    # ── FSM ───────────────────────────────────────────────────────────────
    status          = FSMField(default=ClippingJobStatus.INITIALIZING)
    celery_task_id  = models.CharField(max_length=255, blank=True)
    started_at      = models.DateTimeField(null=True, blank=True)
    completed_at    = models.DateTimeField(null=True, blank=True)
    failed_at       = models.DateTimeField(null=True, blank=True)
    last_error      = models.TextField(blank=True)

    @property
    def total_cost_usd(self):
        return (self.transcription_cost_usd or 0) + (self.analysis_cost_usd or 0)

    @property
    def platform(self):
        return self.social_account.platform
```

**FSM States:** `INITIALIZING → DOWNLOADING → TRANSCRIBING → ANALYZING → AWAITING_CLIP_APPROVAL → RENDERING → DISTRIBUTING → COMPLETED`
Also: `FAILED`, `PAUSED`

**FSM Transitions:** unchanged from existing implementation.

---

### 6.2 `ClipCandidate`
**No changes.** Keep exactly as existing:
- `clipping_job` FK, `start_sec`, `end_sec`, `title`, `hook_text`, `caption_template`, `relevance_score`, `reason`, `transcript_excerpt`, `status`, `approved`, `approved_at`, `approved_by`, `rejection_reason`, `render_gates`
- Validation: duration 30–180s, no overlap ±1s

---

### 6.3 `ClipLayoutConfig`
**No changes.** Keep exactly as existing:
- `candidate` OneToOne, `render_mode`, `render_format`, `manual_crop_*`, `region_a_*`, `region_b_*`, `stack_ratio`, `face_detected`, `detection_confidence`, `preview_image`

---

### 6.4 `ClipRenderTemplate` (Modified)

```python
class ClipRenderTemplate(ClipRenderStyleMixin, BaseAbstractModel):
    # Removed: channel OneToOneField
    # Added:
    name        = models.CharField(max_length=100, default="Default Template")
    is_default  = models.BooleanField(default=False)
    # All 36 style fields inherited from ClipRenderStyleMixin

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True),
                name="unique_default_render_template"
            )
        ]

    def save(self, *args, **kwargs):
        # If setting this as default, unset others
        if self.is_default:
            ClipRenderTemplate.objects.exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    def to_style_defaults(self) -> dict:
        return {field: getattr(self, field) for field in self.STYLE_FIELD_NAMES}
```

**Migration note:** Drop the `channel` column and unique constraint on it. Add `name` and `is_default` columns. Create one default template via data migration.

---

### 6.5 `ClipStyleConfig` (Modified)

```python
class ClipStyleConfig(ClipRenderStyleMixin, BaseAbstractModel):
    candidate       = models.OneToOneField(ClipCandidate, on_delete=models.CASCADE, related_name="style_config")
    # NEW: track which template seeded this config
    render_template = models.ForeignKey(
        ClipRenderTemplate, null=True, blank=True, on_delete=models.SET_NULL
    )
    intro_asset     = models.ForeignKey("ClipMediaAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    outro_asset     = models.ForeignKey("ClipMediaAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    music_asset     = models.ForeignKey("ClipMusicAsset", null=True, blank=True, on_delete=models.SET_NULL)
    translated_transcript_json = models.JSONField(null=True, blank=True)
    preview_image   = models.ImageField(upload_to="clipping/style_previews/", blank=True, null=True)
    # All 36 style fields inherited from ClipRenderStyleMixin
```

---

### 6.6 `ClipTimedOverlay`
**No changes.** Keep as existing.

---

### 6.7 `ClipRender`
**No changes.** Keep as existing:
- `candidate` FK, `format`, `video_file`, `file_size_bytes`, `render_duration_sec`, `include_captions`, `include_title_card`, `include_branding`, `render_config`, `status`, `celery_task_id`, `started_at`, `completed_at`, `last_error`, `paused_at_stage`

---

### 6.8 `ClipRenderStageResult`
**No changes.** Keep as existing:
- `render` FK, `stage_name`, `stage_order`, `status`, `output_file`, `started_at`, `completed_at`, `duration_sec`, `last_error`

---

### 6.9 `ClipMediaAsset` (Modified)

```python
class ClipMediaAsset(BaseAbstractModel):
    # Removed: channel FK
    asset_type   = models.CharField(max_length=10, choices=MediaAssetType.choices)  # INTRO | OUTRO
    name         = models.CharField(max_length=255)
    file         = models.FileField(upload_to="clipping/media_assets/")
    duration_sec = models.FloatField(null=True, blank=True)  # auto-detected via signal
    is_active    = models.BooleanField(default=True)
    thumbnail    = models.ImageField(upload_to="clipping/media_assets/thumbs/", blank=True, null=True)
```

---

### 6.10 `ClipMusicAsset` (Modified)

```python
class ClipMusicAsset(BaseAbstractModel):
    # Removed: channel FK
    name         = models.CharField(max_length=255)
    file         = models.FileField(upload_to="clipping/music_assets/")
    duration_sec = models.FloatField(null=True, blank=True)  # auto-detected via signal
    bpm          = models.FloatField(null=True, blank=True)
    genre        = models.CharField(max_length=100, blank=True)
    is_active    = models.BooleanField(default=True)
    waveform_file = models.FileField(upload_to="clipping/music_assets/waveforms/", blank=True, null=True)
```

---

### 6.11 `ClipPost`
**No changes.** Keep as existing:
- `render` FK, `social_account` FK, `caption`, `title`, `hashtags`, `scheduled_at`, `posted_at`, `status`, `platform_post_id`, `platform_url`, `celery_task_id`, `last_error`, `views`, `likes`, `comments`, `shares`, `revenue_est_usd`, `last_analytics_sync`

---

### 6.12 `analysis_manifest` JSON Schema

Stored in `ClippingJob.analysis_manifest`:

```json
{
  "schema_version": "2.0",
  "transcript": [
    { "word": "hello", "start": 0.12, "end": 0.45, "confidence": 0.99, "speaker_id": "SPEAKER_00" }
  ],
  "speakers": [
    {
      "id": "SPEAKER_00",
      "label": null,
      "total_talk_time": 142.5,
      "segments": [
        { "start": 0.0, "end": 8.3 },
        { "start": 12.1, "end": 45.7 }
      ],
      "face_samples": [
        { "timestamp": 1.0, "bbox": { "x": 120, "y": 80, "w": 200, "h": 250 } }
      ]
    }
  ],
  "scene_cuts": [0.0, 12.4, 38.9, 91.2],
  "ai_clip_suggestions": [
    {
      "start": 45.2,
      "end": 112.7,
      "score": 9.2,
      "reason": "Strong opinion with emotional arc and clear punchline",
      "hook_suggestion": "You've been doing this completely wrong...",
      "title_suggestion": "The real reason your content doesn't grow",
      "dominant_speakers": ["SPEAKER_00"]
    }
  ],
  "waveform_url": "/media/clipping/waveforms/uuid.json",
  "thumbnail_strip_url": "/media/clipping/thumbnails/uuid.jpg",
  "completed_at": "2026-04-06T10:23:00Z"
}
```

---

## 7. FSM — ClippingJob State Machine

### States
```
INITIALIZING          → Job created, nothing started
DOWNLOADING           → download_source_video task running
TRANSCRIBING          → transcribe_video task running
ANALYZING             → analyze_clips task running (includes diarization + scene detection)
AWAITING_CLIP_APPROVAL → Analysis complete, operator must review candidates
RENDERING             → render_clip tasks running for approved candidates
DISTRIBUTING          → All renders complete, post_clip tasks running
COMPLETED             → All posts distributed
FAILED                → Any task hit unrecoverable error
PAUSED                → Operator manually paused the job
```

### Transitions
| Method | From → To |
|--------|-----------|
| `begin_download()` | INITIALIZING → DOWNLOADING |
| `begin_transcription()` | DOWNLOADING → TRANSCRIBING |
| `begin_analysis()` | TRANSCRIBING → ANALYZING |
| `await_clip_approval()` | ANALYZING → AWAITING_CLIP_APPROVAL |
| `begin_rendering()` | AWAITING_CLIP_APPROVAL → RENDERING |
| `begin_distribution()` | RENDERING → DISTRIBUTING |
| `mark_completed()` | DISTRIBUTING → COMPLETED |
| `mark_failed(error, trace)` | any → FAILED |
| `pause()` | any → PAUSED |
| `resume_to_approval()` | PAUSED → AWAITING_CLIP_APPROVAL |
| `resume_to_rendering()` | PAUSED → RENDERING |
| `retry_transcription()` | FAILED → TRANSCRIBING |
| `retry_analysis()` | FAILED → ANALYZING |

### Note: `begin_rendering()` Trigger
After analysis, the job transitions to `AWAITING_CLIP_APPROVAL` and waits. The operator reviews candidates, approves the ones they want, then explicitly calls `POST /api/v1/clipping/jobs/{id}/start-render/`. That view:
1. Verifies at least one candidate is `APPROVED`
2. Dispatches `render_clip.delay(candidate.id)` for each `APPROVED` candidate
3. Calls `job.begin_rendering()`, saves

There is **no auto-approval path**. Auto-approve logic is fully removed.

---

## 8. Celery Task Architecture

### Queue Configuration
```python
CELERY_TASK_ROUTES = {
    "***REMOVED***.clipping.tasks.download_source_video": {"queue": "clipping"},
    "***REMOVED***.clipping.tasks.transcribe_video":      {"queue": "clipping"},
    "***REMOVED***.clipping.tasks.analyze_clips":         {"queue": "clipping"},
    "***REMOVED***.clipping.tasks.preview_clip_layout":   {"queue": "clipping"},
    "***REMOVED***.clipping.tasks.preview_clip_style":    {"queue": "clipping"},
    "***REMOVED***.clipping.tasks.render_clip":           {"queue": "rendering"},
    "***REMOVED***.clipping.tasks.post_clip":             {"queue": "clipping"},
    "***REMOVED***.clipping.tasks.sync_clip_analytics":   {"queue": "analytics"},
}
```

Workers: `clipping` queue (medium concurrency, 4 workers), `rendering` queue (low concurrency, 2 workers — CPU-bound FFmpeg), `analytics` queue (2 workers, low priority).

### SSE Integration in Tasks

All tasks that transition state must emit an SSE event after saving. Use the `emit_job_event` helper:

```python
# ***REMOVED***/clipping/sse.py

import json
import redis
from django.conf import settings

_redis = redis.from_url(settings.REDIS_URL)

def emit_job_event(job_id: str, event_type: str, data: dict):
    """Publish an event to the Redis pub/sub channel for a clipping job."""
    payload = json.dumps({"type": event_type, "job_id": job_id, **data})
    _redis.publish(f"clipping:job:{job_id}", payload)
```

### `download_source_video(clipping_job_id)` — No logic change

Emits after status transitions:
```python
emit_job_event(str(job.id), "status_changed", {"status": job.status})
```

### `transcribe_video(clipping_job_id)` — No logic change

Emits after status transitions.

### `analyze_clips(clipping_job_id)` — Modified

**Old auto-approve block is removed entirely.**

**New: diarization + scene detection run in parallel sub-tasks, then GPT analysis.**

```python
@shared_task(bind=True, queue="clipping", max_retries=2, default_retry_delay=60)
def analyze_clips(self, clipping_job_id: str):
    job = ClippingJob.objects.select_related("social_account").get(id=clipping_job_id)

    # 1. Speaker diarization (PyAnnote)
    diarization_result = run_speaker_diarization(job.downloaded_file.path)

    # 2. Scene detection (PySceneDetect)
    scene_cuts = run_scene_detection(job.downloaded_file.path)

    # 3. Face detection per speaker segment (MediaPipe)
    face_mappings = run_face_detection_for_speakers(
        job.downloaded_file.path, diarization_result
    )

    # 4. Merge transcript + diarization (word-level speaker assignment)
    enriched_transcript = merge_transcript_with_diarization(
        job.transcript_json, diarization_result
    )

    # 5. GPT-4o: clip analysis with enriched context
    service = ClipAnalysisService(job)
    candidates = service.analyze(
        enriched_transcript=enriched_transcript,
        diarization=diarization_result,
        scene_cuts=scene_cuts,
    )

    # 6. Build + save analysis_manifest
    manifest = build_analysis_manifest(
        enriched_transcript, diarization_result, face_mappings,
        scene_cuts, candidates
    )
    job.analysis_manifest = manifest

    # 7. Transition (no auto-approve, always wait for operator)
    job.await_clip_approval()
    job.save(update_fields=["status", "analysis_manifest", "analysis_cost_usd", "analysis_provider"])

    emit_job_event(str(job.id), "analysis_complete", {
        "status": job.status,
        "candidate_count": len(candidates),
    })
```

### `render_clip(clip_candidate_id, start_from_stage=1, clip_render_id=None)` — No logic change

Emits on gate pause, stage completion, render failure:
```python
emit_job_event(str(candidate.clipping_job_id), "render_update", {
    "candidate_id": str(candidate.id),
    "render_id": str(render.id),
    "render_status": render.status,
    "stage": render.paused_at_stage,
})
```

### New Analysis Helper Functions

```python
# ***REMOVED***/clipping/analysis_helpers.py

def run_speaker_diarization(video_path: str) -> dict:
    """Run PyAnnote diarization. Returns segment list per speaker."""
    # See §10 for full implementation

def run_scene_detection(video_path: str) -> list[float]:
    """Run PySceneDetect. Returns list of scene cut timestamps in seconds."""
    from scenedetect import detect, ContentDetector
    scenes = detect(video_path, ContentDetector())
    return [scene[0].get_seconds() for scene in scenes]

def run_face_detection_for_speakers(video_path: str, diarization: dict) -> dict:
    """Run MediaPipe face detection sampled at key moments per speaker segment."""
    # See §10 for full implementation

def merge_transcript_with_diarization(transcript_json: dict, diarization: dict) -> list[dict]:
    """Assign speaker_id to each word based on time overlap with diarization segments."""
    words = []
    for segment in transcript_json.get("segments", []):
        for word_data in segment.get("words", []):
            speaker_id = _find_speaker_at_time(
                word_data["start"], diarization["segments"]
            )
            words.append({
                "word": word_data["word"].strip(),
                "start": word_data["start"],
                "end": word_data["end"],
                "confidence": word_data.get("probability", 1.0),
                "speaker_id": speaker_id,
            })
    return words

def build_analysis_manifest(transcript, diarization, face_mappings, scene_cuts, candidates) -> dict:
    """Assemble the full analysis_manifest JSON."""
    ...
```

---

## 9. Render Pipeline — All 10 Stages

The pipeline in `***REMOVED***/services/media/clip_render_pipeline.py` is **unchanged** except:
- `PipelineRenderConfig` no longer has a `channel` field
- `TrimAndCropStage` uses the upgraded `SpeakerDetectionService` (§10)

### Stage Summary (no changes to stages 2–10)

| # | Stage | Condition | Key FFmpeg Op |
|---|-------|-----------|---------------|
| 1 | `TrimAndCropStage` | Always | Trim + crop (CENTER/SMART/SPATIAL) |
| 2 | `IntroConcatStage` | `intro_asset` set | Prepend intro with optional xfade |
| 3 | `HookStage` | `hook_text` + `hook_enabled` | drawtext title card or overlay |
| 4 | `CaptionTranslationStage` | `caption_translate_to` set | LLM translation, no video change |
| 5 | `CaptionStage` | `caption_enabled` + transcript | ASS subtitle burn via libass |
| 6 | `WatermarkStage` | `watermark_enabled` | drawtext or overlay at corner |
| 7 | `TimedOverlayStage` | overlays exist | Multi-overlay filter_complex pass |
| 8 | `ProgressBarStage` | `progress_bar_enabled` | drawbox with W*t/duration expression |
| 9 | `OutroConcatStage` | `outro_asset` set | Append outro with optional xfade |
| 10 | `MusicMixStage` | `music_enabled` + `music_asset` | amix with loop, volume, fade |

### Gate-Eligible Stages
Gates can be set at stages: **1, 3, 5, 8** (same as existing implementation).

### `PipelineRenderConfig` (Modified)

```python
@dataclass
class PipelineRenderConfig:
    source_path:      Path
    output_path:      Path
    start_sec:        float
    end_sec:          float
    hook_text:        str
    transcript_json:  dict
    render_id:        str
    # Removed: channel field
    # Added: social_account_platform for format/behaviour hints
    social_account_platform: str = "tiktok"
    layout_config:    ClipLayoutConfig | None = None
    style_config:     ClipStyleConfig | None = None
    timed_overlays:   list = field(default_factory=list)
    width:            int = 1080
    height:           int = 1920
    fps:              int = 30
    crf:              int = 18
    preset:           str = "slow"
    audio_bitrate:    str = "192k"
```

---

## 10. Speaker Detection — Upgraded

**File:** `***REMOVED***/services/media/speaker_detection.py`

Replacing OpenCV Haar cascade with **MediaPipe + PyAnnote**.

### Architecture

```
Source Video
     │
     ├──► PyAnnote Audio (full audio)
     │    └──► Diarization segments [{speaker_id, start, end}]
     │
     ├──► Whisper (already done in transcribe_video task)
     │    └──► Word-level transcript
     │
     └──► MediaPipe Face Detection (sampled frames)
          └──► Face bboxes per timestamp

Merge ──► Enriched analysis_manifest
```

### `SpeakerDetectionService` (New Implementation)

```python
# ***REMOVED***/services/media/speaker_detection.py

import mediapipe as mp
import cv2
import numpy as np
from pyannote.audio import Pipeline as PyannotePipeline
from pathlib import Path
from dataclasses import dataclass


@dataclass
class SpeakerCropResult:
    crop_x:      int
    crop_w:      int
    crop_h:      int
    confidence:  float
    face_detected: bool
    speaker_id:  str | None = None


@dataclass
class DiarizationSegment:
    speaker_id: str
    start:      float
    end:        float


class SpeakerDetectionService:

    def __init__(self):
        self._face_detector = None
        self._diarizer = None

    def _get_face_detector(self):
        if self._face_detector is None:
            self._face_detector = mp.solutions.face_detection.FaceDetection(
                model_selection=1,           # full-range model
                min_detection_confidence=0.5
            )
        return self._face_detector

    def _get_diarizer(self):
        if self._diarizer is None:
            self._diarizer = PyannotePipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=settings.HUGGINGFACE_TOKEN,
            )
        return self._diarizer

    def diarize(self, video_path: str) -> list[DiarizationSegment]:
        """Run full speaker diarization on the audio of a video file.
        Extracts audio to temp WAV, runs PyAnnote, returns segment list."""
        import subprocess, tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            audio_path = tmp.name

        subprocess.run([
            "ffmpeg", "-y", "-i", video_path,
            "-ac", "1", "-ar", "16000", "-vn", audio_path
        ], check=True, capture_output=True)

        diarizer = self._get_diarizer()
        diarization = diarizer(audio_path)

        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append(DiarizationSegment(
                speaker_id=speaker,
                start=turn.start,
                end=turn.end,
            ))
        return segments

    def detect_faces_for_segment(
        self,
        video_path: str,
        start_sec: float,
        end_sec: float,
        sample_every_n_frames: int = 5,
    ) -> list[dict]:
        """Sample frames in a time range and return face bboxes per sampled timestamp."""
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        start_frame = int(start_sec * fps)
        end_frame = int(end_sec * fps)
        detector = self._get_face_detector()
        results = []

        for frame_num in range(start_frame, end_frame, sample_every_n_frames):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if not ret:
                break
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            detection = detector.process(frame_rgb)
            timestamp = frame_num / fps
            faces = []
            if detection.detections:
                for d in detection.detections:
                    bbox = d.location_data.relative_bounding_box
                    faces.append({
                        "x": int(bbox.xmin * frame_width),
                        "y": int(bbox.ymin * frame_height),
                        "w": int(bbox.width * frame_width),
                        "h": int(bbox.height * frame_height),
                        "confidence": d.score[0],
                    })
            results.append({"timestamp": timestamp, "faces": faces})

        cap.release()
        return results

    def detect(
        self,
        video_path: str,
        start_sec: float,
        end_sec: float,
        manual_crop_x: float | None = None,
        manual_crop_y: float | None = None,
        manual_crop_w: float | None = None,
        manual_crop_h: float | None = None,
    ) -> SpeakerCropResult:
        """Primary method called from TrimAndCropStage for SMART_CROP mode.
        Returns optimal crop window centred on detected faces.
        Falls back to centre crop if no faces found."""

        cap = cv2.VideoCapture(video_path)
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        # Manual crop override takes full precedence
        if all(v is not None for v in [manual_crop_x, manual_crop_y, manual_crop_w, manual_crop_h]):
            return SpeakerCropResult(
                crop_x=int(manual_crop_x * frame_width),
                crop_w=int(manual_crop_w * frame_width),
                crop_h=int(manual_crop_h * frame_height),
                confidence=1.0,
                face_detected=True,
            )

        face_data = self.detect_faces_for_segment(video_path, start_sec, end_sec)

        # Collect all face centre X positions across sampled frames
        face_centers_x = []
        total_samples = len(face_data)
        samples_with_face = 0

        for sample in face_data:
            if sample["faces"]:
                samples_with_face += 1
                # Pick highest-confidence face in frame
                best = max(sample["faces"], key=lambda f: f["confidence"])
                face_centers_x.append(best["x"] + best["w"] // 2)

        if not face_centers_x:
            # Fallback: centre crop
            crop_w = int(frame_height * 9 / 16)
            crop_x = (frame_width - crop_w) // 2
            return SpeakerCropResult(
                crop_x=crop_x, crop_w=crop_w, crop_h=frame_height,
                confidence=0.0, face_detected=False
            )

        # Median face X to reduce jitter
        median_x = int(np.median(face_centers_x))
        crop_w = int(frame_height * 9 / 16)
        crop_x = median_x - crop_w // 2
        # Clamp to video bounds
        crop_x = max(0, min(crop_x, frame_width - crop_w))
        confidence = samples_with_face / total_samples

        return SpeakerCropResult(
            crop_x=crop_x, crop_w=crop_w, crop_h=frame_height,
            confidence=confidence, face_detected=True
        )
```

### `TrimAndCropStage` — Updated Call Site

```python
# In TrimAndCropStage.run():
service = SpeakerDetectionService()
result = service.detect(
    video_path=str(input_path),
    start_sec=self.config.start_sec,
    end_sec=self.config.end_sec,
    manual_crop_x=layout.manual_crop_x,
    manual_crop_y=layout.manual_crop_y,
    manual_crop_w=layout.manual_crop_w,
    manual_crop_h=layout.manual_crop_h,
)
# Write back to layout_config (same as existing)
layout.face_detected = result.face_detected
layout.detection_confidence = result.confidence
layout.save(update_fields=["face_detected", "detection_confidence"])
```

---

## 11. Gate Mechanism

**Unchanged from existing implementation.** Documented here for completeness.

- Operator sets `candidate.render_gates` (JSON list of stage orders, e.g. `[1, 3, 5]`) via the API
- `render_clip` task passes `candidate.render_gates` as `pause_after_stages` to `ClipRenderPipeline.run()`
- After each stage, pipeline checks: `if stage.order in pause_after_stages → raise GatePausedException(stage_order)`
- Task catches `GatePausedException`, sets `render.status = PAUSED_AT_GATE`, `render.paused_at_stage = N`, returns cleanly
- Operator reviews intermediate output (video file from `ClipRenderStageResult.output_file`) via the frontend
- **Continue:** `POST /api/v1/clipping/renders/{id}/resume/` → dispatches `render_clip.delay(start_from_stage=N+1, clip_render_id=render.id)`
- **Re-run from stage:** `POST /api/v1/clipping/renders/{id}/rerun/{stage_order}/` → same as resume but from a different start

---

## 12. SSE — Real-Time Status Streaming

### Approach: Django SSE via Redis Pub/Sub

No Django Channels. SSE is implemented as a standard Django view that holds an HTTP connection open and streams events from a Redis pub/sub channel.

### Implementation

```python
# ***REMOVED***/clipping/sse.py

import json
import redis
from django.conf import settings
from django.http import StreamingHttpResponse

_redis_client = redis.from_url(settings.REDIS_URL)


def emit_job_event(job_id: str, event_type: str, data: dict):
    """Publish event to job's Redis channel. Called from Celery tasks."""
    payload = json.dumps({
        "type": event_type,
        "job_id": job_id,
        **data,
    })
    _redis_client.publish(f"clipping:job:{job_id}", payload)


def job_event_stream(job_id: str):
    """Generator that yields SSE-formatted strings from Redis pub/sub."""
    pubsub = _redis_client.pubsub()
    pubsub.subscribe(f"clipping:job:{job_id}")
    try:
        # Send initial heartbeat
        yield "event: connected\ndata: {}\n\n"
        for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                yield f"data: {data}\n\n"
    finally:
        pubsub.unsubscribe(f"clipping:job:{job_id}")
        pubsub.close()
```

```python
# In ClippingJobViewSet (views.py):
from .sse import job_event_stream
from rest_framework.decorators import action
from django.http import StreamingHttpResponse

@action(detail=True, methods=["get"], url_path="stream")
def stream(self, request, pk=None):
    """SSE endpoint. Next.js connects here to receive real-time job updates."""
    job = self.get_object()
    response = StreamingHttpResponse(
        job_event_stream(str(job.id)),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"   # Disable nginx buffering
    return response
```

### SSE Event Catalog

All events emitted via `emit_job_event()`:

| `type` | Emitted By | Payload Fields |
|--------|-----------|----------------|
| `status_changed` | Any task on FSM transition | `status` |
| `analysis_complete` | `analyze_clips` | `status`, `candidate_count` |
| `render_update` | `render_clip` | `candidate_id`, `render_id`, `render_status`, `stage` |
| `render_stage_complete` | `render_clip` (per stage) | `render_id`, `stage_order`, `stage_name`, `duration_sec` |
| `render_paused` | `render_clip` on gate | `render_id`, `candidate_id`, `paused_at_stage` |
| `render_complete` | `render_clip` on success | `render_id`, `candidate_id`, `video_url` |
| `render_failed` | `render_clip` on exception | `render_id`, `candidate_id`, `error` |
| `post_complete` | `post_clip` on success | `post_id`, `platform_url` |
| `job_failed` | Any task `mark_failed()` | `error`, `stage` |
| `preview_ready` | `preview_clip_layout` | `layout_config_id`, `preview_url` |

### Next.js SSE Client Pattern

```typescript
// hooks/useJobStream.ts
export function useJobStream(jobId: string) {
  const [events, setEvents] = useState<JobEvent[]>([]);
  
  useEffect(() => {
    if (!jobId) return;
    const es = new EventSource(`/api/v1/clipping/jobs/${jobId}/stream/`, {
      withCredentials: true,
    });
    es.onmessage = (e) => {
      const event: JobEvent = JSON.parse(e.data);
      setEvents(prev => [...prev, event]);
    };
    es.onerror = () => es.close();
    return () => es.close();
  }, [jobId]);

  return events;
}
```

---

## 13. REST API — DRF Contracts

### Router Setup

```python
# config/urls.py
from rest_framework.routers import DefaultRouter
from ***REMOVED***.clipping.views import (
    ClippingJobViewSet, ClipCandidateViewSet, ClipRenderViewSet,
    ClipLayoutConfigViewSet, ClipStyleConfigViewSet,
    ClipTimedOverlayViewSet, ClipMediaAssetViewSet,
    ClipMusicAssetViewSet, ClipRenderTemplateViewSet, ClipPostViewSet,
)

router = DefaultRouter()
router.register(r"clipping/jobs",             ClippingJobViewSet,         basename="clipping-job")
router.register(r"clipping/candidates",       ClipCandidateViewSet,       basename="clip-candidate")
router.register(r"clipping/renders",          ClipRenderViewSet,          basename="clip-render")
router.register(r"clipping/layout-configs",   ClipLayoutConfigViewSet,    basename="clip-layout")
router.register(r"clipping/style-configs",    ClipStyleConfigViewSet,     basename="clip-style")
router.register(r"clipping/overlays",         ClipTimedOverlayViewSet,    basename="clip-overlay")
router.register(r"clipping/media-assets",     ClipMediaAssetViewSet,      basename="clip-media-asset")
router.register(r"clipping/music-assets",     ClipMusicAssetViewSet,      basename="clip-music-asset")
router.register(r"clipping/render-templates", ClipRenderTemplateViewSet,  basename="clip-render-template")
router.register(r"clipping/posts",            ClipPostViewSet,            basename="clip-post")

urlpatterns = [
    path("api/v1/", include(router.urls)),
]
```

---

### `ClippingJobViewSet`

```
GET    /api/v1/clipping/jobs/                       List all jobs
POST   /api/v1/clipping/jobs/                       Create job
GET    /api/v1/clipping/jobs/{id}/                  Job detail (full, with candidates)
PATCH  /api/v1/clipping/jobs/{id}/                  Update label/metadata
DELETE /api/v1/clipping/jobs/{id}/                  Cancel + soft delete

POST   /api/v1/clipping/jobs/{id}/start-render/     Trigger render for all APPROVED candidates
POST   /api/v1/clipping/jobs/{id}/approve-all/      Approve all PROPOSED candidates
POST   /api/v1/clipping/jobs/{id}/retry/            Retry from a failed state (body: {"from_stage": "transcription"})
GET    /api/v1/clipping/jobs/{id}/stream/           SSE stream for real-time events
```

**Create Job Request:**
```json
POST /api/v1/clipping/jobs/
{
  "social_account": "uuid",
  "source_type": "YOUTUBE_URL",
  "source_url": "https://youtube.com/watch?v=...",
  "clips_requested": 5
}
```
**Response 201:** Full job object with `status: "INITIALIZING"`. Task `download_source_video.delay(job.id)` is dispatched on create.

**Start Render Request:**
```json
POST /api/v1/clipping/jobs/{id}/start-render/
{}
```
**Response 200:**
```json
{
  "dispatched_renders": 3,
  "candidate_ids": ["uuid1", "uuid2", "uuid3"],
  "job_status": "RENDERING"
}
```

---

### `ClipCandidateViewSet`

```
GET    /api/v1/clipping/candidates/                 List (filterable: ?job={id}&status=PROPOSED)
GET    /api/v1/clipping/candidates/{id}/            Full detail with layout + style configs
PATCH  /api/v1/clipping/candidates/{id}/            Update label/render_gates

POST   /api/v1/clipping/candidates/{id}/approve/    Approve candidate
POST   /api/v1/clipping/candidates/{id}/reject/     Reject candidate (body: {"reason": "..."})
POST   /api/v1/clipping/candidates/{id}/undo-reject/ Reset to PROPOSED

POST   /api/v1/clipping/candidates/{id}/trigger-preview/  Fire preview_clip_layout task
GET    /api/v1/clipping/candidates/{id}/preview-status/   Check if preview_image is ready
```

**Approve Response 200:**
```json
{
  "id": "uuid",
  "status": "APPROVED",
  "approved": true,
  "approved_at": "2026-04-06T11:02:00Z"
}
```

---

### `ClipLayoutConfigViewSet`

```
GET    /api/v1/clipping/layout-configs/{id}/        Get layout config for candidate
PATCH  /api/v1/clipping/layout-configs/{id}/        Update any layout field

POST   /api/v1/clipping/layout-configs/{id}/reset-crop/  Clear manual_crop_* fields
```

**Update Layout PATCH body example:**
```json
{
  "render_mode": "SPATIAL_STACK",
  "render_format": "VERTICAL_9_16",
  "region_a_x": 0.0,
  "region_a_y": 0.0,
  "region_a_w": 1.0,
  "region_a_h": 0.5,
  "region_b_x": 0.0,
  "region_b_y": 0.5,
  "region_b_w": 1.0,
  "region_b_h": 0.5,
  "stack_ratio": 0.45
}
```

---

### `ClipStyleConfigViewSet`

```
GET    /api/v1/clipping/style-configs/{id}/         Get style config
PATCH  /api/v1/clipping/style-configs/{id}/         Update any style field (auto-save)

POST   /api/v1/clipping/style-configs/{id}/apply-template/  Re-apply a render template
        Body: {"template_id": "uuid"}
```

---

### `ClipTimedOverlayViewSet`

```
GET    /api/v1/clipping/overlays/?candidate={id}    List overlays for candidate
POST   /api/v1/clipping/overlays/                   Create overlay
PATCH  /api/v1/clipping/overlays/{id}/              Update overlay
DELETE /api/v1/clipping/overlays/{id}/              Delete overlay
```

---

### `ClipRenderViewSet`

```
GET    /api/v1/clipping/renders/?candidate={id}     List renders for candidate
GET    /api/v1/clipping/renders/{id}/               Render detail with all stage results
GET    /api/v1/clipping/renders/{id}/download/      Returns signed download URL for video_file

POST   /api/v1/clipping/renders/{id}/resume/        Resume PAUSED_AT_GATE render
POST   /api/v1/clipping/renders/{id}/rerun/{stage_order}/  Re-run from specific stage
```

**Render Detail Response 200:**
```json
{
  "id": "uuid",
  "candidate_id": "uuid",
  "status": "PAUSED_AT_GATE",
  "paused_at_stage": 3,
  "format": "VERTICAL_9_16",
  "started_at": "...",
  "stages": [
    {
      "stage_order": 1,
      "stage_name": "TrimAndCrop",
      "status": "COMPLETED",
      "duration_sec": 12.4,
      "output_file_url": "/media/..."
    },
    {
      "stage_order": 2,
      "stage_name": "IntroConcat",
      "status": "SKIPPED",
      "duration_sec": null
    },
    {
      "stage_order": 3,
      "stage_name": "Hook",
      "status": "COMPLETED",
      "duration_sec": 3.1,
      "output_file_url": "/media/..."
    }
  ]
}
```

---

### `ClipMediaAssetViewSet`

```
GET    /api/v1/clipping/media-assets/               List (filterable: ?asset_type=INTRO)
POST   /api/v1/clipping/media-assets/               Create (multipart/form-data with file)
GET    /api/v1/clipping/media-assets/{id}/          Detail
PATCH  /api/v1/clipping/media-assets/{id}/          Rename / toggle is_active
DELETE /api/v1/clipping/media-assets/{id}/          Delete
GET    /api/v1/clipping/media-assets/{id}/preview-url/  Signed URL
```

---

### `ClipMusicAssetViewSet`

```
GET    /api/v1/clipping/music-assets/               List
POST   /api/v1/clipping/music-assets/               Upload
GET    /api/v1/clipping/music-assets/{id}/          Detail
PATCH  /api/v1/clipping/music-assets/{id}/          Update metadata
DELETE /api/v1/clipping/music-assets/{id}/          Delete
GET    /api/v1/clipping/music-assets/{id}/preview-url/  Signed URL
```

---

### `ClipRenderTemplateViewSet`

```
GET    /api/v1/clipping/render-templates/           List all templates
POST   /api/v1/clipping/render-templates/           Create new template
GET    /api/v1/clipping/render-templates/{id}/      Detail
PATCH  /api/v1/clipping/render-templates/{id}/      Update style fields
DELETE /api/v1/clipping/render-templates/{id}/      Delete (cannot delete if is_default)

POST   /api/v1/clipping/render-templates/{id}/set-default/  Mark as default
```

---

### `ClipPostViewSet`

```
GET    /api/v1/clipping/posts/?render={id}          List posts for a render
GET    /api/v1/clipping/posts/{id}/                 Post detail with analytics
POST   /api/v1/clipping/posts/{id}/sync-analytics/  Trigger analytics sync
```

---

## 14. Global Asset Library

All `ClipMediaAsset` and `ClipMusicAsset` records are now global (no `channel` FK). They are accessible across all jobs.

### Upload Flow (Large Files)

For video/audio files, use pre-signed upload to avoid routing large files through Django:

```
1. POST /api/v1/clipping/media-assets/upload-url/
   Body: {"filename": "intro.mp4", "content_type": "video/mp4"}
   Response: {"upload_url": "https://minio.../presigned...", "key": "clipping/media_assets/uuid.mp4"}

2. PUT {upload_url}   [client uploads directly to MinIO/S3]

3. POST /api/v1/clipping/media-assets/
   Body: {"name": "My Intro", "asset_type": "INTRO", "file_key": "clipping/media_assets/uuid.mp4"}
   → Creates record, signal fires detect_media_asset_duration (ffprobe)
   → Thumbnail generated in background
```

### `ClipRenderTemplate` Bootstrap

On first deploy, run a data migration that creates one global default template:

```python
def create_default_template(apps, schema_editor):
    ClipRenderTemplate = apps.get_model("clipping", "ClipRenderTemplate")
    ClipRenderTemplate.objects.get_or_create(
        is_default=True,
        defaults={
            "name": "Default Template",
            "caption_enabled": True,
            "caption_style": "WORD_BY_WORD",
            "caption_font": "Montserrat-Bold",
            "caption_color": "#FFFFFF",
            "caption_stroke_color": "#000000",
            "caption_stroke_width": 3,
            "caption_position": "BOTTOM",
            "caption_animation": "POP",
            "hook_enabled": True,
            "hook_style": "TITLE_CARD",
            "hook_duration_sec": 3,
            "music_enabled": False,
            "watermark_enabled": False,
            "progress_bar_enabled": False,
        }
    )
```

---

## 15. Frontend — Next.js Screens & Integration

### Repo & Stack
- **Separate repo** from Django backend
- **Next.js 15** (App Router)
- **TypeScript**
- **TanStack Query** — server state, API calls
- **Zustand** — local UI state
- **Konva.js** — crop region canvas editor
- **WaveSurfer.js** — waveform display
- **Tailwind CSS** — styling
- **shadcn/ui** — base components

### API Base Config

```typescript
// lib/api.ts
export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export async function apiRequest<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
```

---

### Screen 1: Jobs Dashboard (`/clipping`)

**Purpose:** Overview of all clipping jobs.

**Data:** `GET /api/v1/clipping/jobs/`

**UI:**
- Table: job title (from `source_title`), social account (avatar + username + platform icon), status pill, created date, cost, action buttons
- Status pills: colour-coded per FSM state (INITIALIZING=grey, DOWNLOADING/TRANSCRIBING/ANALYZING=blue pulse, AWAITING_CLIP_APPROVAL=amber, RENDERING=blue, COMPLETED=green, FAILED=red)
- Filters: status tabs at top
- "New Job" button → opens job creation modal/drawer
- Row click → navigates to job detail

**New Job Form (modal):**
- Social account selector (dropdown of connected accounts with platform icons)
- Source type toggle: YouTube URL / Direct URL / Upload
- URL input or file drag-and-drop
- Clips requested: number input (default 5)
- Submit → `POST /api/v1/clipping/jobs/` → redirect to job detail on 201

---

### Screen 2: Job Detail (`/clipping/[jobId]`)

**Purpose:** See job status, review AI candidates, approve/reject, start render.

**Data:**
- `GET /api/v1/clipping/jobs/{id}/` — job + candidates
- SSE stream: `GET /api/v1/clipping/jobs/{id}/stream/`

**Layout:**
- **Top:** Job header (title, social account, status, cost, duration)
- **FSM Pipeline Tracker:** Horizontal stepper showing all FSM states. Current state animated. Completed states checked.
- **Analysis Timeline** (shown once `AWAITING_CLIP_APPROVAL`):
  - Full-width timeline with source video duration
  - Waveform rendered from `analysis_manifest.waveform_url`
  - Speaker activity bands (colour-coded per speaker from diarization)
  - Scene cut markers as vertical lines
  - AI suggestion regions as highlighted ranges with score labels
  - Video player synced with timeline (click region → seek player)
- **Candidates Panel** (shown once `AWAITING_CLIP_APPROVAL`):
  - Card per candidate: thumbnail, title, score badge, time range, hook text, reason
  - Approve / Reject buttons per card
  - "Approve All" bulk button
  - "Start Render" button — only enabled when ≥1 candidate approved

**SSE event handling:**
- `status_changed` → update FSM tracker pill
- `analysis_complete` → reveal candidates panel, stop loading state
- `render_update` → navigate user to candidate render view or update render progress inline

---

### Screen 3: Candidate Configuration (`/clipping/[jobId]/candidates/[candidateId]`)

**Purpose:** Configure layout, style, overlays, and gates for a single candidate before or after render.

**Data:**
- `GET /api/v1/clipping/candidates/{id}/` — candidate detail
- Includes nested: `layout_config`, `style_config`, `timed_overlays`

**Layout: Two-column**

#### Left Column: Layout Editor

**Mode Selector:** Toggle buttons — `SMART_CROP` | `SPATIAL_STACK` | `CENTER_CROP`

**SMART_CROP sub-editor:**
- Canvas (Konva.js) showing a representative source frame (mid-clip)
- Green overlay rectangle showing current crop window
- User can drag/resize the crop rectangle → updates `manual_crop_x/y/w/h` via `PATCH /api/v1/clipping/layout-configs/{id}/`
- "Reset to Auto" button → `POST /api/v1/clipping/layout-configs/{id}/reset-crop/`
- "Generate Preview" button → `POST /api/v1/clipping/candidates/{id}/trigger-preview/` → polls `GET /api/v1/clipping/candidates/{id}/preview-status/` → shows preview JPEG

**SPATIAL_STACK sub-editor:**
- Canvas with two draggable/resizable rectangles (Region A = blue, Region B = green)
- Stack ratio slider (30%–80%)
- Region A and B labels (editable)
- Live output preview pane: shows composited 9:16 output as user adjusts

**CENTER_CROP sub-editor:**
- Static explanation card: "Crops horizontal centre of frame to 9:16. No configuration needed."

#### Right Column: Accordion panels

**Captions Panel:**
- Enable/disable toggle
- Style selector: `WORD_BY_WORD` | `CHUNKED` | `EMOJI_ACCENT` | `LOWER_THIRD`
- Font family (dropdown from `GET /api/v1/clipping/media-assets/?asset_type=FONT` or system fonts)
- Font size slider
- Colour pickers: text, stroke, background
- Position selector: TOP / CENTER / BOTTOM
- Animation: POP / FADE / NONE
- Translate to: language selector (blank = no translation)
- All fields auto-save on change via `PATCH /api/v1/clipping/style-configs/{id}/`

**Hook Panel:**
- Enable/disable toggle
- Style: `TITLE_CARD` | `OVERLAY_TOP` | `OVERLAY_CENTER`
- Hook text (pre-filled from AI, editable)
- Duration, font, colour, background

**Watermark Panel:**
- Enable/disable toggle
- Type: TEXT | IMAGE
- Text input or image upload
- Position selector (4 corners)
- Opacity slider

**Progress Bar Panel:**
- Enable/disable toggle
- Position: TOP | BOTTOM
- Colour picker, height slider

**Music Panel:**
- Enable/disable toggle
- Music asset picker: dropdown from `GET /api/v1/clipping/music-assets/`
- Volume slider (dB)
- Fade in / fade out duration inputs
- Preview audio player for selected track

**Intro/Outro Panel:**
- Intro: dropdown from media assets (type=INTRO) + transition selector
- Outro: dropdown from media assets (type=OUTRO) + transition selector

**Timed Overlays Panel:**
- List of existing overlays with inline editable rows (text, start/end, position)
- "Add Overlay" button → `POST /api/v1/clipping/overlays/` → new row appears
- Delete per row

**Gates Panel:**
- Checkboxes for stages 1, 3, 5, 8
- Updates `candidate.render_gates` via `PATCH /api/v1/clipping/candidates/{id}/`

---

### Screen 4: Render Detail (`/clipping/[jobId]/renders/[renderId]`)

**Purpose:** Monitor render execution, see per-stage status, manage gate pauses.

**Data:**
- `GET /api/v1/clipping/renders/{id}/` — render + stages
- SSE: inherited from parent job stream (already open on the job page)

**Layout:**
- **Left:** Stage pipeline list
  - One row per stage (1–10)
  - Status icon: pending (grey circle), running (blue spinner), completed (green check), skipped (grey dash), failed (red X)
  - Stage name, duration when complete
  - "Re-run from here" button (appears on completed stages when render is not active)
  - Error message expandable on FAILED stages
  - "View output" link on COMPLETED stages → shows intermediate video player
- **Right:**
  - Video player: shows latest available stage output file
  - If `PAUSED_AT_GATE`: amber banner "Paused after Stage N. Review output above then continue."
    - "Continue" button → `POST /api/v1/clipping/renders/{id}/resume/`
    - "Edit Config" link → back to candidate config screen
  - If `COMPLETED`: green banner with download button → `GET /api/v1/clipping/renders/{id}/download/`
  - If `FAILED`: red banner with error + "Retry from last stage" button

---

### Screen 5: Asset Library (`/clipping/assets`)

**Tabs:** Intros | Outros | Music | Render Templates

**Intros / Outros tab:**
- Grid of `ClipMediaAsset` items
- Card: thumbnail, name, duration
- Upload button → multipart upload or pre-signed flow
- Delete / rename per item

**Music tab:**
- List of `ClipMusicAsset` items
- Row: name, genre, BPM, duration, waveform mini-vis, audio preview player
- Upload, delete, rename

**Render Templates tab:**
- List of `ClipRenderTemplate` items
- Card: name, "Default" badge if `is_default`, key style settings summary
- "Set as Default" button per card
- "Edit" → inline form for all 36 style fields
- "New Template" → create form

---

## 16. Django Project Structure

```
***REMOVED***/
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py            ← DRF router registered here
│   ├── asgi.py
│   └── celery.py
│
├── clipping/              ← Core app (all clipping domain logic)
│   ├── models.py          ← All models as documented in §6
│   ├── serializers.py     ← DRF serializers for all models
│   ├── views/
│   │   ├── jobs.py        ← ClippingJobViewSet
│   │   ├── candidates.py  ← ClipCandidateViewSet + ClipLayoutConfigViewSet + ClipStyleConfigViewSet
│   │   ├── renders.py     ← ClipRenderViewSet
│   │   ├── overlays.py    ← ClipTimedOverlayViewSet
│   │   └── assets.py      ← ClipMediaAssetViewSet + ClipMusicAssetViewSet + ClipRenderTemplateViewSet
│   ├── tasks.py           ← All Celery tasks
│   ├── services.py        ← ClipAnalysisService
│   ├── analysis_helpers.py ← Diarization, scene detection, manifest building
│   ├── sse.py             ← emit_job_event + job_event_stream
│   ├── signals.py         ← Modified signals (no channel refs)
│   ├── constants.py       ← Enums + PLATFORM_RENDER_MODE_DEFAULTS
│   ├── apps.py
│   └── migrations/
│
└── services/
    └── media/
        ├── clip_render_pipeline.py      ← ClipRenderPipeline (unchanged)
        ├── speaker_detection.py         ← Rebuilt with MediaPipe + PyAnnote
        ├── render_stages/
        │   ├── trim_crop.py             ← Uses upgraded SpeakerDetectionService
        │   ├── intro_outro.py
        │   ├── hook.py
        │   ├── captions.py
        │   ├── watermark.py
        │   ├── timed_overlays.py
        │   ├── progress_bar.py
        │   └── music_mix.py
        └── analysis_helpers.py          ← Symlink or import from clipping/analysis_helpers.py
```

---

## 17. Tech Stack

### Backend
| Component | Technology |
|-----------|-----------|
| Web Framework | Django 5.2 |
| REST API | Django REST Framework |
| Task Queue | Celery 5.x + Redis |
| Real-time | SSE via Redis Pub/Sub (no Django Channels needed) |
| Video Download | yt-dlp |
| Transcription | OpenAI Whisper API |
| Speaker Diarization | PyAnnote Audio 3.1 (`pyannote/speaker-diarization-3.1`) |
| Face Detection | MediaPipe (`mediapipe` Python SDK) |
| Scene Detection | PySceneDetect |
| AI Analysis | OpenAI GPT-4o |
| Video Processing | FFmpeg (subprocess) |
| Face Detection (legacy, remove) | OpenCV Haar cascade → replaced by MediaPipe |
| Caption Rendering | ASS via libass (ffmpeg filter) |
| Object Storage | MinIO / AWS S3 via django-storages |
| Database | PostgreSQL |
| FSM | django-fsm |
| Monitoring | Logfire / OpenTelemetry |

### Frontend (separate repo)
| Component | Technology |
|-----------|-----------|
| Framework | Next.js 15 (App Router) |
| Language | TypeScript |
| Styling | Tailwind CSS + shadcn/ui |
| Server State | TanStack Query |
| Client State | Zustand |
| Canvas / Crop Editor | Konva.js |
| Waveform | WaveSurfer.js |
| Real-time | Native EventSource (SSE) |
| Video Player | Custom `<video>` with controls |

### New Python Dependencies
```
mediapipe>=0.10
pyannote.audio>=3.1
scenedetect[opencv]>=0.6
```

### Removed Python Dependencies
```
# opencv-python (Haar cascade) — MediaPipe ships its own OpenCV
# channels / channels-redis — SSE replaces Django Channels
```

---

## 18. Implementation Phases

### Phase 1 — Model Migration & API Layer (Backend)

Goal: Existing models updated, Channel removed, full DRF API live, Django templates deleted.

- [ ] Write migration: drop `channel` FK from `ClippingJob`
- [ ] Write migration: add `social_account` FK to `ClippingJob`
- [ ] Write migration: drop `channel` FK from `ClipRenderTemplate`, add `name` + `is_default`
- [ ] Write migration: drop `channel` FK from `ClipMediaAsset`
- [ ] Write migration: drop `channel` FK from `ClipMusicAsset`
- [ ] Write data migration: create one default `ClipRenderTemplate`
- [ ] Add `analysis_manifest` JSONField to `ClippingJob`
- [ ] Add `render_template` FK to `ClipStyleConfig`
- [ ] Update `constants.py`: add `PLATFORM_RENDER_MODE_DEFAULTS`, `PLATFORM_FORMAT_DEFAULTS`
- [ ] Update signals: remove `create_clip_render_template_for_channel`, update layout + style creation signals
- [ ] Remove auto-approve block from `analyze_clips` task
- [ ] Write DRF serializers for all models
- [ ] Write DRF ViewSets (jobs, candidates, renders, layout, style, overlays, assets, templates, posts)
- [ ] Register router in `config/urls.py`
- [ ] Implement SSE: `sse.py` + `emit_job_event` + add `/stream/` action to `ClippingJobViewSet`
- [ ] Add `emit_job_event()` calls to all tasks at status transition points
- [ ] Delete all files in `***REMOVED***/clipping/views/` (old template views)
- [ ] Delete all templates in `***REMOVED***/templates/clipping/`

### Phase 2 — Speaker Detection Upgrade (Backend)

Goal: Replace OpenCV Haar cascade with MediaPipe + PyAnnote throughout.

- [ ] Install and configure `mediapipe`, `pyannote.audio`
- [ ] Rewrite `SpeakerDetectionService` (§10)
- [ ] Write `analysis_helpers.py`: `run_speaker_diarization`, `run_scene_detection`, `run_face_detection_for_speakers`, `merge_transcript_with_diarization`, `build_analysis_manifest`
- [ ] Update `analyze_clips` task to run diarization + scene detection + face mapping, build manifest
- [ ] Update `ClipAnalysisService.analyze()` to accept and use `enriched_transcript` + `diarization`
- [ ] Update `TrimAndCropStage` to use new `SpeakerDetectionService.detect()` signature

### Phase 3 — Next.js Frontend

Goal: All 5 screens functional, real-time SSE integrated.

- [ ] Set up Next.js 15 repo with Tailwind, shadcn/ui, TanStack Query, Zustand
- [ ] `lib/api.ts` — base API client
- [ ] `hooks/useJobStream.ts` — SSE hook
- [ ] Screen 1: Jobs Dashboard + New Job modal
- [ ] Screen 2: Job Detail with FSM tracker + analysis timeline + candidates panel
- [ ] Screen 3: Candidate Configuration (crop editor, all style panels)
- [ ] Screen 4: Render Detail with stage pipeline + gate controls
- [ ] Screen 5: Asset Library (media, music, templates)
- [ ] Konva.js crop region canvas editor
- [ ] WaveSurfer.js timeline integration with analysis manifest data
- [ ] SSE event dispatch to update all screens in real-time

### Phase 4 — Polish & Integration

- [ ] Pre-signed upload flow for large video/audio assets
- [ ] Render template management UI
- [ ] Timed overlays panel with inline editing
- [ ] Per-stage output video preview in render detail
- [ ] Analytics display in post detail
- [ ] Error handling: per-task retry UI, failure banners, error message display

---

## Appendix A — Constants Reference

```python
# ***REMOVED***/clipping/constants.py

from django.db import models


class RenderMode(models.TextChoices):
    SMART_CROP    = "SMART_CROP"
    SPATIAL_STACK = "SPATIAL_STACK"
    CENTER_CROP   = "CENTER_CROP"


class RenderFormat(models.TextChoices):
    VERTICAL_9_16  = "VERTICAL_9_16"
    LANDSCAPE_16_9 = "LANDSCAPE_16_9"
    SQUARE_1_1     = "SQUARE_1_1"


class CaptionStyle(models.TextChoices):
    WORD_BY_WORD = "WORD_BY_WORD"
    CHUNKED      = "CHUNKED"
    LOWER_THIRD  = "LOWER_THIRD"
    EMOJI_ACCENT = "EMOJI_ACCENT"


class CaptionPosition(models.TextChoices):
    TOP    = "TOP"
    CENTER = "CENTER"
    BOTTOM = "BOTTOM"


class CaptionAnimation(models.TextChoices):
    POP  = "POP"
    FADE = "FADE"
    NONE = "NONE"


class HookStyle(models.TextChoices):
    TITLE_CARD     = "TITLE_CARD"
    OVERLAY_TOP    = "OVERLAY_TOP"
    OVERLAY_CENTER = "OVERLAY_CENTER"


class TransitionStyle(models.TextChoices):
    NONE       = "NONE"
    CROSSFADE  = "CROSSFADE"
    FADE_BLACK = "FADE_BLACK"
    WIPE_LEFT  = "WIPE_LEFT"
    WIPE_RIGHT = "WIPE_RIGHT"


class WatermarkType(models.TextChoices):
    TEXT  = "TEXT"
    IMAGE = "IMAGE"


class WatermarkPosition(models.TextChoices):
    TOP_LEFT     = "TOP_LEFT"
    TOP_RIGHT    = "TOP_RIGHT"
    BOTTOM_LEFT  = "BOTTOM_LEFT"
    BOTTOM_RIGHT = "BOTTOM_RIGHT"


class ProgressBarPosition(models.TextChoices):
    TOP    = "TOP"
    BOTTOM = "BOTTOM"


class MediaAssetType(models.TextChoices):
    INTRO = "INTRO"
    OUTRO = "OUTRO"


class ClippingJobStatus(models.TextChoices):
    INITIALIZING          = "INITIALIZING"
    DOWNLOADING           = "DOWNLOADING"
    TRANSCRIBING          = "TRANSCRIBING"
    ANALYZING             = "ANALYZING"
    AWAITING_CLIP_APPROVAL = "AWAITING_CLIP_APPROVAL"
    RENDERING             = "RENDERING"
    DISTRIBUTING          = "DISTRIBUTING"
    COMPLETED             = "COMPLETED"
    FAILED                = "FAILED"
    PAUSED                = "PAUSED"


class CandidateStatus(models.TextChoices):
    PROPOSED    = "PROPOSED"
    APPROVED    = "APPROVED"
    REJECTED    = "REJECTED"
    RENDERING   = "RENDERING"
    RENDERED    = "RENDERED"
    DISTRIBUTING = "DISTRIBUTING"
    DISTRIBUTED = "DISTRIBUTED"


# Platform-driven defaults (replaces channel.default_render_mode)
PLATFORM_RENDER_MODE_DEFAULTS = {
    "tiktok":    RenderMode.SMART_CROP,
    "youtube":   RenderMode.CENTER_CROP,
    "instagram": RenderMode.SMART_CROP,
}

PLATFORM_FORMAT_DEFAULTS = {
    "tiktok":    RenderFormat.VERTICAL_9_16,
    "youtube":   RenderFormat.LANDSCAPE_16_9,
    "instagram": RenderFormat.SQUARE_1_1,
}
```

---

*Reelforge — Clipping Feature KRD v2.0*
*Stack: Django 5.2 · DRF · Celery · FFmpeg · MediaPipe · PyAnnote · Whisper · GPT-4o · PySceneDetect · Next.js 15 · TanStack Query · Konva.js*
