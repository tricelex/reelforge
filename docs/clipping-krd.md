# Clipping Feature — Knowledge Reference Document (KRD)

> Last updated: 2026-04-06
> Covers: models, tasks, services, render pipeline, views, URLs, signals, templates, constants

---

## Table of Contents

1. [Overview](#overview)
2. [End-to-End Pipeline Flow](#end-to-end-pipeline-flow)
3. [Models](#models)
4. [Celery Tasks](#celery-tasks)
5. [Services](#services)
6. [Render Pipeline](#render-pipeline)
7. [Render Stages (1–10)](#render-stages-110)
8. [Speaker Detection](#speaker-detection)
9. [Views](#views)
10. [URL Routing](#url-routing)
11. [Signals](#signals)
12. [Templates](#templates)
13. [Constants](#constants)
14. [Gate Mechanism](#gate-mechanism)
15. [Auto-Approval Logic](#auto-approval-logic)

---

## Overview

The **clipping feature** is a self-contained sub-pipeline within Reelforge that takes an existing video (YouTube URL, direct URL, or uploaded file) and turns it into short-form social clips.

The flow is: **download → transcribe → AI analysis → operator approval → 10-stage render → social post → analytics**.

Apps involved:
- `reelforge/clipping/` — all domain models, tasks, views, signals
- `reelforge/services/media/` — render pipeline and all render stages
- `reelforge/services/media/speaker_detection.py` — OpenCV face tracking for SMART_CROP

Dashboard URL namespace: `clipping:` (mounted at `/app/clipping/`)

---

## End-to-End Pipeline Flow

```
[Operator creates ClippingJob]
         │ status: INITIALIZING
         ▼
[download_source_video task]
  - yt_dlp for YouTube/direct URLs, or uses uploaded file
  - Extracts source_title, source_duration_sec
  - Transitions: INITIALIZING → DOWNLOADING → TRANSCRIBING
         │
         ▼
[transcribe_video task]
  - Extracts 16kHz mono MP3 audio (kept under 25MB)
  - Runs Whisper → stores transcript_text + transcript_json (word-level timestamps)
  - Records transcription_provider, transcription_cost_usd
  - Transitions: TRANSCRIBING → ANALYZING
         │
         ▼
[analyze_clips task]
  - Calls ClipAnalysisService.analyze()
  - LLM identifies N clip candidates (30–180s, no overlaps)
  - Creates ClipCandidate records with title, hook_text, caption_template, relevance_score
  - Signal auto-creates ClipLayoutConfig + ClipStyleConfig per candidate
  - If auto_approve_clips=True on all target_accounts:
      → auto-approves all candidates, triggers render_clip tasks
      → Transitions: ANALYZING → RENDERING
  - Otherwise:
      → Transitions: ANALYZING → AWAITING_CLIP_APPROVAL
         │
         ▼
[Operator reviews candidates at /app/clipping/<job_id>/]
  - Approve / Reject each candidate
  - Configure per-candidate: layout, style, timed overlays, render gates
  - Clicks "Start Render" → JobStartRenderView fires render_clip.delay() per approved candidate
  - Job transitions: AWAITING_CLIP_APPROVAL → RENDERING
         │
         ▼
[render_clip task] (runs independently per candidate)
  - Creates ClipRender record (or resumes existing)
  - Instantiates ClipRenderPipeline with layout_config, style_config, timed_overlays
  - Passes render_gates as pause_after_stages
  - Runs up to 10 stages sequentially:
      1. TrimAndCrop  (always)
      2. IntroConcat  (if intro_asset set)
      3. Hook         (if hook_text + hook_enabled)
      4. CaptionTranslation  (if caption_translate_to set)
      5. Caption      (if caption_enabled)
      6. Watermark    (if watermark_enabled)
      7. TimedOverlay (if overlays exist)
      8. ProgressBar  (if progress_bar_enabled)
      9. OutroConcat  (if outro_asset set)
     10. MusicMix     (if music_enabled + music_asset set)
  - At each gate stage → raises GatePausedException
      → render.status = PAUSED_AT_GATE, render.paused_at_stage = N
      → Operator reviews at /app/clipping/renders/<render_id>/
      → Clicks "Continue" → ResumeRenderView → render_clip resumes from stage N+1
  - On completion:
      → candidate.status = RENDERED
      → Creates ClipPost records for each target_account
      → Fires post_clip.delay() per ClipPost
         │
         ▼
[post_clip task]
  - Calls distribution provider (Instagram/TikTok/YouTube Shorts)
  - Sets platform_post_id, platform_url, posted_at
  - ClipPost.status → POSTED
  - Job transitions eventually: RENDERING → DISTRIBUTING → COMPLETED
         │
         ▼
[sync_clip_analytics task] (periodic)
  - Fetches views, likes, comments, shares, revenue_est_usd per ClipPost
  - Updates last_analytics_sync
```

---

## Models

All models live in `reelforge/clipping/models.py` and inherit `BaseAbstractModel` (UUID PK, created_at, updated_at, soft delete).

---

### ClippingJob

The top-level FSM-orchestrated record for a single clipping run.

**File:** `reelforge/clipping/models.py`

| Field | Type | Notes |
|-------|------|-------|
| `channel` | FK → Channel | owning channel |
| `target_accounts` | M2M → SocialAccount | platforms to post clips to |
| `source_type` | CharField | `YOUTUBE_URL`, `DIRECT_URL`, `UPLOAD` |
| `source_url` | URLField | URL for download-based sources |
| `source_video_file` | FileField | uploaded video for UPLOAD type |
| `downloaded_file` | FileField | processed source file after download |
| `source_title` | CharField | extracted from source metadata |
| `source_duration_sec` | FloatField | duration in seconds |
| `transcript_text` | TextField | plain-text transcript |
| `transcript_json` | JSONField | Whisper JSON with word-level `segments` |
| `transcription_provider` | CharField | e.g. `whisper` |
| `transcription_cost_usd` | DecimalField | cost from transcription API |
| `clips_requested` | PositiveIntegerField | how many candidates to generate |
| `analysis_provider` | CharField | LLM provider used for analysis |
| `analysis_cost_usd` | DecimalField | LLM cost for analysis |
| `agent_run_id` | CharField | OpenAI Agents SDK run ID |
| `agent_cost_usd` | DecimalField | agent run cost |
| `celery_task_id` | CharField | currently running task ID |
| `status` | FSMField | see transitions below |
| `started_at` | DateTimeField | |
| `completed_at` | DateTimeField | |
| `failed_at` | DateTimeField | |
| `last_error` | TextField | error message on FAILED |

**FSM States:** `INITIALIZING → DOWNLOADING → TRANSCRIBING → ANALYZING → AWAITING_CLIP_APPROVAL → RENDERING → DISTRIBUTING → COMPLETED`  
Also: `FAILED`, `PAUSED`

**FSM Transitions:**

| Method | From | To |
|--------|------|----|
| `begin_download()` | INITIALIZING | DOWNLOADING |
| `begin_transcription()` | DOWNLOADING | TRANSCRIBING |
| `begin_analysis()` | TRANSCRIBING | ANALYZING |
| `await_clip_approval()` | ANALYZING | AWAITING_CLIP_APPROVAL |
| `begin_rendering()` | AWAITING_CLIP_APPROVAL, ANALYZING | RENDERING |
| `begin_distribution()` | RENDERING | DISTRIBUTING |
| `mark_completed()` | DISTRIBUTING | COMPLETED |
| `mark_failed(error, trace)` | any | FAILED |
| `pause()` | any | PAUSED |
| `resume_to_approval()` | PAUSED | AWAITING_CLIP_APPROVAL |
| `resume_to_rendering()` | PAUSED | RENDERING |
| `retry_transcription()` | FAILED | TRANSCRIBING |

**Properties:**
- `total_cost_usd` — sums `transcription_cost_usd + analysis_cost_usd`

---

### ClipCandidate

A proposed clip segment identified by LLM analysis.

| Field | Type | Notes |
|-------|------|-------|
| `clipping_job` | FK → ClippingJob | |
| `start_sec` | FloatField | start time in source video |
| `end_sec` | FloatField | end time in source video |
| `title` | CharField | AI-generated clip title |
| `hook_text` | CharField | opening hook sentence |
| `caption_template` | TextField | social caption with hashtags |
| `relevance_score` | FloatField 0–10 | AI ranking |
| `reason` | TextField | why AI selected this clip |
| `transcript_excerpt` | TextField | words from transcript between start/end |
| `status` | CharField | PROPOSED, APPROVED, REJECTED, RENDERING, RENDERED, DISTRIBUTING, DISTRIBUTED |
| `approved` | BooleanField null | True/False/None |
| `approved_at` | DateTimeField | |
| `approved_by` | FK → User | |
| `rejection_reason` | TextField | |
| `render_gates` | JSONField (list[int]) | stage orders where pipeline pauses (e.g. `[1, 3, 5]`) |

**Properties:**
- `duration_sec` → `end_sec - start_sec`

**Validation:**
- Duration must be 30–180 seconds
- `end_sec > start_sec`
- No overlapping candidates within ±1 second

---

### ClipRender

One render attempt for a candidate. A candidate may have multiple renders (retries, format variations).

| Field | Type | Notes |
|-------|------|-------|
| `candidate` | FK → ClipCandidate | |
| `format` | CharField | `VERTICAL_9_16`, `LANDSCAPE_16_9`, `SQUARE_1_1` |
| `video_file` | FileField | final output MP4 |
| `file_size_bytes` | FloatField | |
| `render_duration_sec` | FloatField | wall-clock render time |
| `include_captions` | BooleanField | |
| `include_title_card` | BooleanField | |
| `include_branding` | BooleanField | |
| `render_config` | JSONField | saved pipeline config snapshot |
| `status` | CharField | PENDING, RUNNING, COMPLETED, FAILED, PAUSED_AT_GATE |
| `celery_task_id` | CharField | |
| `started_at` | DateTimeField | |
| `completed_at` | DateTimeField | |
| `last_error` | TextField | |
| `paused_at_stage` | PositiveIntegerField | which stage triggered the gate pause |

> `status` is a plain `CharField`, **not** FSM-protected. Direct assignment is safe.

---

### ClipPost

A single post to one social account for one render.

| Field | Type | Notes |
|-------|------|-------|
| `render` | FK → ClipRender | |
| `social_account` | FK → SocialAccount | |
| `caption` | TextField | post text |
| `title` | CharField | |
| `hashtags` | ArrayField(CharField) | |
| `scheduled_at` | DateTimeField null | if set, post is scheduled |
| `posted_at` | DateTimeField | |
| `status` | CharField | PENDING, POSTING, POSTED, SCHEDULED, FAILED |
| `platform_post_id` | CharField | returned by platform API |
| `platform_url` | CharField | public URL of post |
| `celery_task_id` | CharField | |
| `last_error` | TextField | |
| `views` | PositiveIntegerField | analytics |
| `likes` | PositiveIntegerField | analytics |
| `comments` | PositiveIntegerField | analytics |
| `shares` | PositiveIntegerField | analytics |
| `revenue_est_usd` | DecimalField | estimated revenue |
| `last_analytics_sync` | DateTimeField | |

---

### ClipLayoutConfig

Per-candidate layout and crop configuration (one per candidate, auto-created by signal).

| Field | Type | Notes |
|-------|------|-------|
| `candidate` | OneToOneField → ClipCandidate | |
| `render_mode` | CharField | `SMART_CROP`, `SPATIAL_STACK`, `CENTER_CROP` |
| `render_format` | CharField | `VERTICAL_9_16`, `LANDSCAPE_16_9`, `SQUARE_1_1` |
| `manual_crop_x/y/w/h` | FloatField null | SMART_CROP manual override (normalized 0–1) |
| `region_a_x/y/w/h` | FloatField null | SPATIAL_STACK top region (normalized) |
| `region_a_label` | CharField | label for region A |
| `region_a_scale` | FloatField | scale factor for region A |
| `region_b_x/y/w/h` | FloatField null | SPATIAL_STACK bottom region |
| `region_b_label` | CharField | |
| `region_b_scale` | FloatField | |
| `stack_ratio` | FloatField 0.3–0.8 | fraction of height for region A |
| `face_detected` | BooleanField | result written back by TrimAndCropStage |
| `detection_confidence` | FloatField | OpenCV detection confidence |
| `preview_image` | ImageField | JPEG preview with crop overlaid |

**Properties:**
- `has_manual_smart_crop` → all four `manual_crop_*` fields are set
- `has_spatial_regions` → all eight `region_*_*` coordinate fields are set

---

### ClipRenderStyleMixin (Abstract)

Shared styling fields inherited by both `ClipRenderTemplate` and `ClipStyleConfig`. 36 fields total across: captions, hook, transitions, watermark, progress bar, music.

**Caption fields:** `caption_enabled`, `caption_style`, `caption_font`, `caption_size`, `caption_color`, `caption_stroke_color`, `caption_stroke_width`, `caption_bg_color`, `caption_position`, `caption_animation`, `caption_language`, `caption_translate_to`, `emoji_keyword_map`

**Hook fields:** `hook_enabled`, `hook_style`, `hook_duration_sec`, `hook_font`, `hook_size`, `hook_color`, `hook_bg_color`, `hook_animation`

**Transition fields:** `intro_transition`, `outro_transition`, `transition_duration_sec`

**Watermark fields:** `watermark_enabled`, `watermark_type`, `watermark_text`, `watermark_image`, `watermark_position`, `watermark_opacity`, `watermark_size`

**Progress bar fields:** `progress_bar_enabled`, `progress_bar_position`, `progress_bar_color`, `progress_bar_height`

**Music fields:** `music_enabled`, `music_volume_db` (dB), `music_fade_in_sec`, `music_fade_out_sec`

**Class attribute:** `STYLE_FIELD_NAMES` — list of all 36 field names for bulk copying

---

### ClipRenderTemplate

Channel-level style defaults. One per channel, auto-created when a Channel is saved.

| Field | Type | Notes |
|-------|------|-------|
| `channel` | OneToOneField → Channel | |
| *(all 36 style fields)* | from ClipRenderStyleMixin | |

**Method:** `to_style_defaults()` → returns dict of all style field values for cloning into `ClipStyleConfig`

---

### ClipStyleConfig

Per-candidate style overrides. Auto-created by signal, pre-populated from `ClipRenderTemplate`.

| Field | Type | Notes |
|-------|------|-------|
| `candidate` | OneToOneField → ClipCandidate | |
| *(all 36 style fields)* | from ClipRenderStyleMixin | |
| `intro_asset` | FK → ClipMediaAsset null | selected intro clip |
| `outro_asset` | FK → ClipMediaAsset null | selected outro clip |
| `music_asset` | FK → ClipMusicAsset null | background music |
| `translated_transcript_json` | JSONField | cached translation (set by CaptionTranslationStage) |
| `preview_image` | ImageField | style preview JPEG |

---

### ClipTimedOverlay

A time-ranged text or image overlay composited onto the final video.

| Field | Type | Notes |
|-------|------|-------|
| `candidate` | FK → ClipCandidate | |
| `overlay_type` | CharField | `TEXT`, `IMAGE` |
| `text` | CharField | for TEXT overlays |
| `image` | ImageField | for IMAGE overlays |
| `start_sec` | FloatField | clip-relative start time |
| `end_sec` | FloatField | clip-relative end time |
| `position_x` | FloatField | normalized X (0–1) |
| `position_y` | FloatField | normalized Y (0–1) |
| `opacity` | FloatField | 0–1 |
| `font_size` | PositiveIntegerField | |
| `font_color` | CharField | hex color |

---

### ClipRenderStageResult

Per-stage execution record. One row per stage per render attempt.

| Field | Type | Notes |
|-------|------|-------|
| `render` | FK → ClipRender | |
| `stage_name` | CharField | human-readable stage name |
| `stage_order` | PositiveIntegerField | 1–10 |
| `status` | CharField | PENDING, RUNNING, COMPLETED, FAILED, SKIPPED |
| `output_file` | FileField | intermediate video output |
| `started_at` | DateTimeField | |
| `completed_at` | DateTimeField | |
| `duration_sec` | FloatField | wall-clock stage time |
| `last_error` | TextField | error on FAILED |

---

### ClipMediaAsset

Intro/outro video library for a channel.

| Field | Type | Notes |
|-------|------|-------|
| `channel` | FK → Channel | |
| `asset_type` | CharField | `INTRO`, `OUTRO` |
| `name` | CharField | |
| `file` | FileField | |
| `duration_sec` | FloatField | auto-detected via ffprobe on save |
| `is_active` | BooleanField | |

---

### ClipMusicAsset

Background music library for a channel.

| Field | Type | Notes |
|-------|------|-------|
| `channel` | FK → Channel | |
| `name` | CharField | |
| `file` | FileField | |
| `duration_sec` | FloatField | auto-detected via ffprobe on save |
| `bpm` | FloatField | |
| `genre` | CharField | |
| `is_active` | BooleanField | |

---

## Celery Tasks

All tasks live in `reelforge/clipping/tasks.py`.

---

### `download_source_video(clipping_job_id)`

| Attribute | Value |
|-----------|-------|
| Queue | `clipping` |
| bind | True |
| max_retries | 3 |
| Retry backoff | `2 ** retries * 60` seconds |

**Logic:**
1. Loads `ClippingJob` by ID
2. If `source_type == UPLOAD`: skips download, uses `source_video_file`
3. If `source_type == YOUTUBE_URL` or `DIRECT_URL`: uses `yt_dlp` to download to temp path, moves to `downloaded_file`
4. Extracts `source_title` and `source_duration_sec` from yt_dlp metadata
5. Calls `job.begin_download()` → `job.begin_transcription()` (saves with `update_fields`)
6. Dispatches `transcribe_video.delay(clipping_job_id)`

---

### `transcribe_video(clipping_job_id)`

| Attribute | Value |
|-----------|-------|
| Queue | `clipping` |
| bind | True |
| max_retries | 3 |
| Retry delay | 120 seconds |

**Logic:**
1. Extracts audio from `downloaded_file` → 16kHz mono MP3 (ffmpeg, stays under 25MB Whisper limit)
2. Sends to Whisper API → receives full transcript with word-level timestamps
3. Stores `transcript_text` (plain text), `transcript_json` (Whisper segments format)
4. Records `transcription_cost_usd` and `transcription_provider`
5. Calls `job.begin_analysis()` and saves
6. Dispatches `analyze_clips.delay(clipping_job_id)`

---

### `analyze_clips(clipping_job_id)`

| Attribute | Value |
|-----------|-------|
| Queue | `clipping` |
| bind | True |
| max_retries | 2 |
| Retry delay | 60 seconds |

**Logic:**
1. Instantiates `ClipAnalysisService(job)`
2. Calls `service.analyze()` → list of `ClipCandidate` instances created
3. Auto-creation signals fire per candidate (ClipLayoutConfig + ClipStyleConfig)
4. **Auto-approve check:** if all `target_accounts` have `auto_approve_clips=True`:
   - Sets all candidates to `status=APPROVED`, `approved=True`
   - Calls `job.begin_rendering()`, dispatches `render_clip.delay()` for each
5. Otherwise: calls `job.await_clip_approval()` and saves
6. Records `analysis_cost_usd` and `analysis_provider` on job

---

### `render_clip(clip_candidate_id, start_from_stage=1, clip_render_id=None)`

| Attribute | Value |
|-----------|-------|
| Queue | `rendering` |
| bind | True |
| max_retries | 2 |
| Retry delay | 300 seconds |
| time_limit | 3600 seconds |

**Logic:**
1. Loads `ClipCandidate` with related `layout_config`, `style_config`, `timed_overlays`
2. If `clip_render_id` provided: loads existing `ClipRender` (resume); else creates new
3. Sets `render.status = RUNNING`, `render.started_at`, saves
4. Builds `PipelineRenderConfig` from all config objects
5. Instantiates `ClipRenderPipeline(config)`
6. Calls `pipeline.run(start_from_stage=start_from_stage, pause_after_stages=candidate.render_gates)`
7. **On `GatePausedException(stage_order=N)`:**
   - Sets `render.status = PAUSED_AT_GATE`, `render.paused_at_stage = N`
   - Saves and returns cleanly (no retry, no error)
8. **On success:**
   - Writes back `face_detected` and `detection_confidence` from TrimAndCropStage result to `layout_config`
   - Sets `render.status = COMPLETED`, `render.completed_at`, `render.video_file`
   - Sets `candidate.status = RENDERED`
   - Creates `ClipPost` for each `target_account` with `should_post=True`
   - Dispatches `post_clip.delay()` for each `ClipPost`
9. **On exception:** sets `render.status = FAILED`, `render.last_error`, raises for retry logic

---

### `preview_clip_layout(layout_config_id)`

| Attribute | Value |
|-----------|-------|
| Queue | `clipping` |
| max_retries | 1 |
| time_limit | 120 seconds |

**Logic:**
1. Loads `ClipLayoutConfig`
2. Seeks to mid-point of clip in source video, extracts one frame (OpenCV)
3. Draws crop region overlays:
   - SMART_CROP → green rectangle
   - SPATIAL_STACK → blue (region A) + green (region B) rectangles
4. Saves JPEG to `layout_config.preview_image`

---

### `preview_clip_style(style_config_id)`

| Attribute | Value |
|-----------|-------|
| Queue | `clipping` |
| max_retries | 1 |
| time_limit | 60 seconds |

**Logic:**
1. Loads `ClipStyleConfig`
2. Extracts mid-clip frame
3. Uses PIL to overlay sample watermark text and caption text
4. Saves JPEG to `style_config.preview_image`

---

### `post_clip(clip_post_id)`

| Attribute | Value |
|-----------|-------|
| Queue | `clipping` |
| max_retries | 3 |
| Retry delay | 120 seconds |

**Logic:**
1. Loads `ClipPost` with related `render`, `social_account`
2. Looks up distribution provider for `social_account.platform`
3. Calls `provider.post_clip(clip_post)` — posts video with caption, hashtags, scheduled_at
4. On success: sets `platform_post_id`, `platform_url`, `posted_at`, `status=POSTED`
5. On failure: sets `status=FAILED`, `last_error`

---

### `sync_clip_analytics(clip_post_id)`

| Attribute | Value |
|-----------|-------|
| Queue | `analytics` |
| max_retries | 2 |

**Logic:**
1. Loads `ClipPost`
2. Calls `provider.get_analytics(clip_post)` for the post's platform
3. Updates `views`, `likes`, `comments`, `shares`, `revenue_est_usd`, `last_analytics_sync`

---

## Services

### `ClipAnalysisService`

**File:** `reelforge/clipping/services.py`

**Constructor:** `ClipAnalysisService(clipping_job: ClippingJob)`

#### `analyze() → list[ClipCandidate]`

1. Calls `_build_prompt(transcript_text)` and `_system_prompt()`
2. Calls `get_llm_provider(job.channel).complete(prompt=..., system=...)`
3. Calls `_parse_llm_response(response_text)` → list of dicts
4. For each dict:
   - Calls `_extract_transcript_excerpt(start_sec, end_sec)`
   - Creates `ClipCandidate` with all AI fields
5. Updates `job.analysis_cost_usd`, `job.analysis_provider`
6. Returns list of created candidates

#### `_extract_transcript_excerpt(start_sec, end_sec) → str`
- Iterates `job.transcript_json["segments"]`
- Collects word tokens where `word.start >= start_sec` and `word.end <= end_sec`
- Returns joined string

#### `_build_prompt(transcript) → str`
- Instructs LLM to find `clips_requested` engaging moments
- Constraints: 30–180 second duration, no overlapping clips
- Requests JSON array with: `start_sec`, `end_sec`, `title`, `hook_text`, `caption_template`, `relevance_score`, `reason`
- Includes channel `niche_category` for context

#### `_system_prompt() → str`
- Sets LLM role as content strategist specializing in short-form video

#### `_parse_llm_response(response_text) → list[dict]`
- Strips markdown code fences (` ```json ` ... ` ``` `)
- Parses JSON
- Returns list of clip dicts

---

## Render Pipeline

**File:** `reelforge/services/media/clip_render_pipeline.py`

### `GatePausedException`

Raised by `ClipRenderPipeline.run()` when a stage completes and the operator requested a pause.

**Attribute:** `stage_order: int` — the stage order number that triggered the pause

---

### `PipelineRenderConfig` (dataclass)

Configuration object passed to `ClipRenderPipeline`.

| Field | Type | Default |
|-------|------|---------|
| `source_path` | Path | required |
| `output_path` | Path | required |
| `start_sec` | float | required |
| `end_sec` | float | required |
| `hook_text` | str | required |
| `transcript_json` | dict | required |
| `layout_config` | ClipLayoutConfig \| None | None |
| `style_config` | ClipStyleConfig \| None | None |
| `timed_overlays` | list[ClipTimedOverlay] | `[]` |
| `render_id` | str | required |
| `channel` | Channel \| None | None |
| `width` | int | 1080 |
| `height` | int | 1920 |
| `fps` | int | 30 |
| `crf` | int | 18 |
| `preset` | str | `"slow"` |
| `audio_bitrate` | str | `"192k"` |

---

### `ClipRenderPipeline`

**Constructor:** `ClipRenderPipeline(config: PipelineRenderConfig)`

#### `run(start_from_stage=1, pause_after_stages=None) → Path`

1. Calls `_build_stages()` to instantiate all 10 `RenderStage` objects
2. If `start_from_stage > 1`:
   - Queries `ClipRenderStageResult` for the last completed stage < `start_from_stage`
   - Uses its `output_file` as `current_path`
   - Deletes all stage results with `stage_order >= start_from_stage` (clean slate for re-run)
3. Iterates stages in order:
   - Skips stages with `order < start_from_stage`
   - Calls `_run_stage(stage, current_path)` → new `current_path`
   - If `stage.order in pause_after_stages`: raises `GatePausedException(stage_order=stage.order)`
4. Copies `current_path` to `config.output_path`
5. Returns `config.output_path`

#### `_run_stage(stage, input_path) → Path`

1. Creates or updates `ClipRenderStageResult` with `status=RUNNING`, `started_at=now`
2. Calls `stage.should_run()`:
   - Returns `False` → marks result `SKIPPED`, returns `input_path` unchanged
3. Calls `stage.run(input_path)` → `output_path`
4. On success: marks result `COMPLETED`, calculates `duration_sec`
5. On exception: marks result `FAILED`, stores `last_error`, raises `RenderStageError`

---

## Render Stages (1–10)

All stages live in `reelforge/services/media/render_stages/`. Each implements `RenderStage` abstract base with `should_run() → bool` and `run(input_path: Path) → Path`.

---

### Stage 1 — `TrimAndCropStage`

**File:** `render_stages/trim_crop.py` | **Always runs**

Trims source to clip boundaries and applies the configured crop mode.

**CENTER_CROP (default):**
- ffmpeg filter: `crop=ih*9/16:ih` — crops horizontal center to 9:16 ratio
- Scales to `width x height` (1080×1920), re-encodes H.264 + AAC

**SMART_CROP:**
- Calls `SpeakerDetectionService.detect(source, start_sec, end_sec)`
- Returns `SpeakerCropResult` with `crop_x`, `crop_w`, `crop_h`, `confidence`, `face_detected`
- If `layout_config.has_manual_smart_crop` → uses manual coordinates instead
- Writes `face_detected` + `detection_confidence` back to `layout_config`
- Falls back to CENTER_CROP if no face detected

**SPATIAL_STACK:**
- Requires `region_a_*` and `region_b_*` coordinates on `layout_config`
- Uses ffmpeg `filter_complex` with two crop+scale chains + `vstack`
- Region A height = `height * stack_ratio`, Region B = `height * (1 - stack_ratio)`

**Output:** `{render_id}_stage1.mp4` — trimmed, cropped, 1080×1920@30fps H.264 + AAC

---

### Stage 2 — `IntroConcatStage`

**File:** `render_stages/intro_outro.py` | **Runs if:** `style_config.intro_asset is not None`

Prepends intro clip before main content.

- Scales intro to match main video dimensions
- **NONE transition:** hard cut via ffmpeg `concat` filter
- **CROSSFADE / FADE_BLACK / WIPE_LEFT / WIPE_RIGHT:** uses `xfade` video filter + `acrossfade` audio filter

**Output:** `{render_id}_stage2.mp4`

---

### Stage 3 — `HookStage`

**File:** `render_stages/hook.py` | **Runs if:** `hook_text` set and `style_config.hook_enabled`

Renders the hook text onto the video.

**TITLE_CARD:** Creates a solid black frame with `drawtext` of `hook_text`, duration = `hook_duration_sec`, then prepends to main video via `concat`

**OVERLAY_TOP / OVERLAY_CENTER:** Burns `drawtext` directly onto video for first `hook_duration_sec` seconds using `enable='between(t,0,duration)'` expression

**Output:** `{render_id}_stage3.mp4`

---

### Stage 4 — `CaptionTranslationStage`

**File:** `render_stages/captions.py` | **Runs if:** `style_config.caption_translate_to` is set

Translates transcript to target language using LLM. Does **not** modify the video.

- Checks `style_config.translated_transcript_json` — skips if already cached (idempotent on retry)
- Calls `get_llm_provider(channel).complete()` to translate all `text` and `word` values in `transcript_json`
- Preserves segment/word structure, timing unchanged
- Saves result to `style_config.translated_transcript_json`
- Returns `input_path` unchanged (video is not modified)

**Output:** `input_path` (pass-through) — data prepared for Stage 5

---

### Stage 5 — `CaptionStage`

**File:** `render_stages/captions.py` | **Runs if:** `style_config.caption_enabled` and `transcript_json` exists

Generates ASS subtitle file and burns captions using libass.

**Uses translated transcript if `translated_transcript_json` is set.**

**Caption styles (via `ASSGenerator`):**

| Style | Behavior |
|-------|----------|
| `WORD_BY_WORD` | Each word timed individually — karaoke effect |
| `CHUNKED` | Groups into 3-word chunks, each chunk displayed together |
| `EMOJI_ACCENT` | Like CHUNKED but appends emoji based on `emoji_keyword_map` dict |
| `LOWER_THIRD` | Full segment text per Whisper segment |

**ASS Format details:**
- Hex colors converted to ASS `&HABBGGRR` format
- Position mapped: `TOP=8`, `CENTER=5`, `BOTTOM=2` (ASS alignment)
- Animation: `POP` → ASS `\t` scale effect, `FADE` → `\fad` tag, `NONE` → plain
- Stroke width from `caption_stroke_width`; background via `\bord` and `\shad`

**ffmpeg command:** `ass=subtitles.ass` filter with `libass` renderer

**Output:** `{render_id}_stage5.mp4` with burned-in captions

---

### Stage 6 — `WatermarkStage`

**File:** `render_stages/watermark.py` | **Runs if:** `style_config.watermark_enabled`

**TEXT watermark:** `drawtext` filter at corner position with `alpha=opacity`

**IMAGE watermark:** `overlay` filter with image file at normalized position, `format=auto` for alpha support

Positions: `TOP_LEFT`, `TOP_RIGHT`, `BOTTOM_LEFT`, `BOTTOM_RIGHT` — mapped to pixel offsets

**Output:** `{render_id}_stage6.mp4`

---

### Stage 7 — `TimedOverlayStage`

**File:** `render_stages/timed_overlays.py` | **Runs if:** `timed_overlays` list is not empty

Composites all timed overlays in a single ffmpeg pass.

- Separates TEXT and IMAGE overlays
- Each overlay uses `enable='between(t,{start_sec},{end_sec})'` expression
- TEXT: `drawtext` filters chained in filter_complex
- IMAGE: `overlay` filters with position + alpha
- All overlays composited in one pass for efficiency

**Output:** `{render_id}_stage7.mp4`

---

### Stage 8 — `ProgressBarStage`

**File:** `render_stages/progress_bar.py` | **Runs if:** `style_config.progress_bar_enabled`

Draws an animated time-driven progress bar using `drawbox`.

- Width expression: `W*t/{duration}` (grows from 0 to full width over video duration)
- Position: `TOP` → y=0; `BOTTOM` → y=H-height
- Height: `progress_bar_height` pixels
- Color: `progress_bar_color`

**Output:** `{render_id}_stage8.mp4`

---

### Stage 9 — `OutroConcatStage`

**File:** `render_stages/intro_outro.py` | **Runs if:** `style_config.outro_asset is not None`

Appends outro clip after main content. Same logic as Stage 2 but appended instead of prepended.

**Output:** `{render_id}_stage9.mp4`

---

### Stage 10 — `MusicMixStage`

**File:** `render_stages/music_mix.py` | **Runs if:** `style_config.music_enabled` and `style_config.music_asset is not None`

Mixes background music under the clip's existing audio.

- If `music_duration < clip_duration`: loops music using `-stream_loop -1`
- Applies `volume={music_volume_db}dB` filter
- Applies `afade=t=in:d={fade_in_sec}` and `afade=t=out:d={fade_out_sec}` if set
- Uses `amix` filter to blend with original audio
- Output duration = original audio duration (music is trimmed/faded to match)

**Output:** `{render_id}_stage10.mp4` — final render

---

## Speaker Detection

**File:** `reelforge/services/media/speaker_detection.py`

### `SpeakerCropResult` (dataclass)

| Field | Type | Notes |
|-------|------|-------|
| `crop_x` | int | left edge of crop window in source pixels |
| `crop_w` | int | width of crop window |
| `crop_h` | int | height of crop window |
| `confidence` | float | fraction of sampled frames with face detected |
| `face_detected` | bool | False if fell back to center crop |

### `SpeakerDetectionService`

Uses **OpenCV Haar cascade** face detector.

#### `detect(video_path, start_sec, end_sec) → SpeakerCropResult`

1. Opens video with `cv2.VideoCapture`
2. Seeks to `start_sec`, samples every Nth frame (default N=5) until `end_sec`
3. Converts each frame to grayscale
4. Runs `CascadeClassifier.detectMultiScale()` on each frame
5. Collects detected face center X positions
6. Computes **median** face_x to smooth jitter across frames
7. Computes crop window: centers `9:16` crop on `median_face_x`, clamped to video bounds
8. Returns `SpeakerCropResult(crop_x, crop_w, crop_h, confidence=detections/total_sampled, face_detected=True)`
9. If no faces found: returns center crop with `face_detected=False`, `confidence=0.0`

---

## Views

All views live in `reelforge/clipping/views/`. All require `StaffRequiredMixin` (staff-only access).

---

### `views/jobs.py`

#### `JobListView` — `GET /clipping/`
Lists all `ClippingJob` records. Optional `?status=STATUS` filter.  
Context: `jobs`, `status_filter`, `status_choices`  
Template: `clipping/job_list.html`

#### `JobDetailView` — `GET /clipping/<job_id>/`
Shows full job detail: metadata, pipeline stage tracker, candidate cards.  
Context: `job`, `candidates` (ordered by `-relevance_score`), `fsm_stages`, `job_completed_stages`  
Template: `clipping/job_detail.html`

#### `JobStatusPartialView` — `GET /clipping/<job_id>/status/`
HTMX polling endpoint. Returns the pipeline stage tracker strip only.  
Template: `clipping/partials/job_status.html`

#### `JobApproveAllView` — `POST /clipping/<job_id>/approve-all/`
Bulk-approves all `PROPOSED` candidates for a job.  
Sets `approved=True`, `status=APPROVED`, `approved_by=request.user`, `approved_at=now` for each.  
Returns full candidates list HTML.

#### `JobStartRenderView` — `POST /clipping/<job_id>/start-render/`
Triggers `render_clip.delay(candidate.id)` for all `APPROVED` candidates.  
Calls `job.begin_rendering()`, saves job.  
Returns `HX-Redirect` to job detail page.

---

### `views/candidates.py`

#### `CandidateDetailView` — `GET /clipping/clips/<candidate_id>/`
Full candidate configuration page.  
Context: `candidate`, `job`, `layout`, `style`, `renders`, `timed_overlays`  
Template: `clipping/candidate_detail.html`

#### `CandidateApproveView` — `POST /clipping/clips/<candidate_id>/approve/`
Sets `approved=True`, `status=APPROVED`, `approved_by`, `approved_at`.  
Returns `candidate_row.html` partial (HTMX swaps the card in place).

#### `CandidateRejectView` — `POST /clipping/clips/<candidate_id>/reject/`
Sets `approved=False`, `status=REJECTED`.  
Returns `candidate_row.html` partial.

#### `CandidateUndoRejectView` — `POST /clipping/clips/<candidate_id>/undo-reject/`
Resets `approved=None`, `status=PROPOSED`.  
Returns `candidate_row.html` partial.

#### `UpdateLayoutConfigView` — `POST /clipping/clips/<candidate_id>/layout/`
Saves `render_mode` and/or `render_format` from POST body.  
Returns refreshed `layout_editor.html` partial.

#### `UpdateLayoutRegionsView` — `POST /clipping/clips/<candidate_id>/layout/regions/`
Saves coordinate fields: `manual_crop_*`, `region_a_*`, `region_b_*`, `stack_ratio`.  
Returns HTTP 200 with no body (`hx-swap="none"`).

#### `ResetSmartCropView` — `POST /clipping/clips/<candidate_id>/layout/reset-crop/`
Clears all `manual_crop_*` fields to `None`.  
Returns refreshed `layout_editor.html` partial.

#### `UpdateStyleConfigView` — `POST /clipping/clips/<candidate_id>/style/`
Saves any style field changes (captions, hook, watermark, music, etc.).  
Handles boolean coercion (checkbox presence = True), int/float parsing.  
Returns HTTP 200 with no body (auto-saves on blur/change via HTMX).

#### `TriggerPreviewView` — `POST /clipping/clips/<candidate_id>/preview/trigger/`
Fires `preview_clip_layout.delay(layout_config.id)`.  
Returns `preview_panel.html` with `polling=True`.

#### `PreviewStatusView` — `GET /clipping/clips/<candidate_id>/preview/status/`
HTMX polling endpoint. Checks if `layout_config.preview_image` exists.  
Returns `preview_panel.html` with `polling=True` if not ready, `polling=False` if ready.

#### `AddOverlayView` — `POST /clipping/clips/<candidate_id>/overlays/add/`
Creates new `ClipTimedOverlay` with default values.  
Returns `overlay_row.html` partial (HTMX appends to list).

#### `UpdateOverlayView` — `POST /clipping/overlays/<overlay_id>/update/`
Saves `text`, `start_sec`, `end_sec`, `position_x`, `position_y`, `font_size`.  
Returns HTTP 200.

#### `DeleteOverlayView` — `POST /clipping/overlays/<overlay_id>/delete/`
Deletes overlay. Returns HTTP 200 (HTMX removes the row).

#### `UpdateRenderGatesView` — `POST /clipping/clips/<candidate_id>/gates/`
Parses comma-separated gate stage numbers from `POST["gates"]`.  
Validates range 1–10, deduplicates, sorts ascending.  
Saves to `candidate.render_gates` (JSONField list).  
Returns `gates_panel.html` partial.

---

### `views/renders.py`

#### `RenderDetailView` — `GET /clipping/renders/<render_id>/`
Shows render execution status: pipeline stages, video preview, pause/resume controls.  
Context: `render`, `candidate`, `layout`, `stages` (all `ClipRenderStageResult`), `is_terminal`  
Template: `clipping/render_detail.html`

#### `StageListPartialView` — `GET /clipping/renders/<render_id>/stages/`
HTMX polling target that refreshes the stage list.  
Sets `is_terminal=True` when render status is `COMPLETED`, `FAILED`, or `PAUSED_AT_GATE`.  
Returns `stage_list.html` partial — HTMX stops polling when `is_terminal=True`.

#### `RerunFromStageView` — `POST /clipping/renders/<render_id>/rerun/<stage_order>/`
Re-runs the pipeline from a specific stage.  
Sets `render.status = RUNNING`, clears `paused_at_stage`, `last_error`.  
Calls `render_clip.delay(candidate_id, start_from_stage=stage_order, clip_render_id=render.id)`.  
Returns `HX-Redirect` to render detail.

#### `ResumeRenderView` — `POST /clipping/renders/<render_id>/resume/`
Resumes a `PAUSED_AT_GATE` render from the next stage.  
Validates `render.status == PAUSED_AT_GATE`.  
Computes `next_stage = render.paused_at_stage + 1`.  
Calls `render_clip.delay(..., start_from_stage=next_stage, clip_render_id=render.id)`.  
Returns `HX-Redirect` to render detail.

---

## URL Routing

**File:** `reelforge/clipping/urls.py` — mounted at `/app/clipping/` (namespace: `clipping`)

| Method | Path | View | Name |
|--------|------|------|------|
| GET | `/clipping/` | `JobListView` | `job-list` |
| GET | `/clipping/<job_id>/` | `JobDetailView` | `job-detail` |
| GET | `/clipping/<job_id>/status/` | `JobStatusPartialView` | `job-status` |
| POST | `/clipping/<job_id>/approve-all/` | `JobApproveAllView` | `job-approve-all` |
| POST | `/clipping/<job_id>/start-render/` | `JobStartRenderView` | `job-start-render` |
| GET | `/clipping/clips/<candidate_id>/` | `CandidateDetailView` | `candidate-detail` |
| POST | `/clipping/clips/<candidate_id>/layout/` | `UpdateLayoutConfigView` | `update-layout` |
| POST | `/clipping/clips/<candidate_id>/layout/regions/` | `UpdateLayoutRegionsView` | `update-layout-regions` |
| POST | `/clipping/clips/<candidate_id>/layout/reset-crop/` | `ResetSmartCropView` | `reset-smart-crop` |
| POST | `/clipping/clips/<candidate_id>/style/` | `UpdateStyleConfigView` | `update-style` |
| POST | `/clipping/clips/<candidate_id>/preview/trigger/` | `TriggerPreviewView` | `trigger-preview` |
| GET | `/clipping/clips/<candidate_id>/preview/status/` | `PreviewStatusView` | `preview-status` |
| POST | `/clipping/clips/<candidate_id>/overlays/add/` | `AddOverlayView` | `add-overlay` |
| POST | `/clipping/overlays/<overlay_id>/update/` | `UpdateOverlayView` | `update-overlay` |
| POST | `/clipping/overlays/<overlay_id>/delete/` | `DeleteOverlayView` | `delete-overlay` |
| POST | `/clipping/clips/<candidate_id>/approve/` | `CandidateApproveView` | `approve-candidate` |
| POST | `/clipping/clips/<candidate_id>/reject/` | `CandidateRejectView` | `reject-candidate` |
| POST | `/clipping/clips/<candidate_id>/undo-reject/` | `CandidateUndoRejectView` | `undo-reject-candidate` |
| POST | `/clipping/clips/<candidate_id>/gates/` | `UpdateRenderGatesView` | `update-gates` |
| GET | `/clipping/renders/<render_id>/` | `RenderDetailView` | `render-detail` |
| GET | `/clipping/renders/<render_id>/stages/` | `StageListPartialView` | `stage-list` |
| POST | `/clipping/renders/<render_id>/rerun/<stage_order>/` | `RerunFromStageView` | `rerun-from-stage` |
| POST | `/clipping/renders/<render_id>/resume/` | `ResumeRenderView` | `resume-render` |

---

## Signals

**File:** `reelforge/clipping/signals.py`

### `on_clipping_job_transition`
- **Trigger:** `post_transition` signal on `ClippingJob`
- **Logic:** When job transitions to `FAILED`, logs the error with `extra={job_id, error}`

### `create_layout_config_for_candidate`
- **Trigger:** `post_save` on `ClipCandidate`, `created=True`
- **Logic:** Auto-creates `ClipLayoutConfig` for the new candidate
  - Uses `candidate.clipping_job.channel.default_render_mode`
  - Pre-populates from `channel.default_layout_config` dict if set

### `create_style_config_for_candidate`
- **Trigger:** `post_save` on `ClipCandidate`, `created=True`
- **Logic:** Auto-creates `ClipStyleConfig` for the new candidate
  - Calls `ClipRenderTemplate.to_style_defaults()` for the channel
  - Copies all 36 style fields from the template to the new config

### `detect_media_asset_duration`
- **Trigger:** `post_save` on `ClipMediaAsset`
- **Logic:** If `file` is set and `duration_sec` is null, runs `ffprobe` to auto-detect duration

### `detect_music_asset_duration`
- **Trigger:** `post_save` on `ClipMusicAsset`
- **Logic:** Same as above for music assets

### `create_clip_render_template_for_channel`
- **Trigger:** Registered manually in `ClippingConfig.ready()` (to avoid circular imports), connected to `post_save` on `Channel`
- **Logic:** Auto-creates `ClipRenderTemplate` when a new `Channel` is created

---

## Templates

All templates are in `reelforge/templates/clipping/`.

| Template | Purpose |
|----------|---------|
| `job_list.html` | Jobs listing page — status filter tabs, table of all jobs |
| `job_detail.html` | Single job — pipeline stage tracker, candidates list with approve/reject |
| `candidate_detail.html` | Candidate config page — two-column: layout editor left, style panels + overlays + gates right |
| `render_detail.html` | Render execution — stage list left, video preview + pause/resume right |
| `partials/layout_editor.html` | Mode selector, format dropdown, sub-editors (smart/spatial/center), preview panel |
| `partials/smart_crop_editor.html` | Preview image with crop overlay, trigger preview button, manual crop inputs |
| `partials/spatial_stack_editor.html` | Region A + B coordinate inputs with labels, stack ratio slider |
| `partials/center_crop_editor.html` | Static explanation (no configurable fields for center crop) |
| `partials/preview_panel.html` | Layout preview image — HTMX polls `every 2s` until image is ready |
| `partials/style_panels.html` | Collapsible accordion: captions, hook, transitions, watermark, progress bar, music — auto-saves on blur/change |
| `partials/gates_panel.html` | Alpine.js checkboxes for gate stages (1, 3, 5, 8) — hidden form auto-submitted on change |
| `partials/candidate_row.html` | Single candidate card — thumbnail, title, time range, relevance score, approve/reject buttons |
| `partials/stage_pill.html` | Single pipeline stage indicator — name, status icon, duration, error expandable, re-run/preview buttons |
| `partials/stage_list.html` | Container for stage pills — HTMX polls `every 2s`, stops when `is_terminal=True` |
| `partials/overlay_row.html` | Single timed overlay row — text, start/end times, position, font size, save/delete |
| `partials/job_status.html` | FSM stage tracker — ordered stages with completed/active/pending states |

---

## Constants

**File:** `reelforge/clipping/constants.py`

| Enum | Values |
|------|--------|
| `RenderMode` | `SMART_CROP`, `SPATIAL_STACK`, `CENTER_CROP` |
| `CaptionStyle` | `WORD_BY_WORD`, `CHUNKED`, `LOWER_THIRD`, `EMOJI_ACCENT` |
| `CaptionPosition` | `TOP`, `CENTER`, `BOTTOM` |
| `CaptionAnimation` | `POP`, `FADE`, `NONE` |
| `HookStyle` | `TITLE_CARD`, `OVERLAY_TOP`, `OVERLAY_CENTER` |
| `TransitionStyle` | `NONE`, `CROSSFADE`, `FADE_BLACK`, `WIPE_LEFT`, `WIPE_RIGHT` |
| `WatermarkType` | `TEXT`, `IMAGE` |
| `WatermarkPosition` | `TOP_LEFT`, `TOP_RIGHT`, `BOTTOM_LEFT`, `BOTTOM_RIGHT` |
| `ProgressBarPosition` | `TOP`, `BOTTOM` |
| `MediaAssetType` | `INTRO`, `OUTRO` |

---

## Gate Mechanism

The gate mechanism lets operators pause the render pipeline mid-run to review intermediate output before continuing.

### How it works

**1. Configuration (operator):**
- On the candidate config page (`/app/clipping/clips/<candidate_id>/`), the `gates_panel.html` shows checkboxes for stages 1, 3, 5, and 8.
- `UpdateRenderGatesView` saves the selected stage orders to `candidate.render_gates` (a JSONField `list[int]`).

**2. Render task:**
- `render_clip` task passes `candidate.render_gates` as `pause_after_stages` to `ClipRenderPipeline.run()`.

**3. Pipeline execution:**
- After each stage completes, `ClipRenderPipeline.run()` checks: `if stage.order in pause_after_stages`.
- If true: raises `GatePausedException(stage_order=stage.order)`.

**4. Task catches exception:**
```python
except GatePausedException as exc:
    render.status = "PAUSED_AT_GATE"
    render.paused_at_stage = exc.stage_order
    render.save(update_fields=["status", "paused_at_stage"])
    return  # no retry, no error — clean exit
```

**5. Operator review:**
- Render detail page shows `PAUSED_AT_GATE` status and which stage caused the pause.
- The intermediate video file is available from `ClipRenderStageResult.output_file` for that stage.
- Operator can view the output and decide:
  - **Continue** → `ResumeRenderView` → `render_clip.delay(start_from_stage=paused_at_stage + 1, clip_render_id=render.id)`
  - **Edit config** → navigate to candidate config, adjust settings, then re-run from a specific stage via `RerunFromStageView`

**6. Resume logic in pipeline:**
- `ClipRenderPipeline.run(start_from_stage=N)`:
  - Queries the last completed stage result with `order < N`
  - Uses its `output_file` as the starting `current_path`
  - Deletes all stage results with `order >= N` (clean slate)
  - Continues from stage N onward

---

## Auto-Approval Logic

After `analyze_clips` creates all `ClipCandidate` records, the task checks:

```python
all_auto = all(
    account.auto_approve_clips
    for account in job.target_accounts.all()
)
```

**If `True` (all target accounts have `auto_approve_clips=True`):**
- All candidates are set to `approved=True`, `status=APPROVED`
- `render_clip.delay(candidate.id)` is dispatched for each immediately
- Job transitions: `ANALYZING → RENDERING`

**If `False` (any account requires manual approval):**
- Job transitions: `ANALYZING → AWAITING_CLIP_APPROVAL`
- Operator reviews candidates at `/app/clipping/<job_id>/`
- After approving desired candidates, clicks "Start Render" → `JobStartRenderView`
- Job transitions: `AWAITING_CLIP_APPROVAL → RENDERING`

---

*Reelforge — Clipping Feature KRD*  
*Stack: Django 5.2 · Celery · ffmpeg · OpenCV · Whisper · Tailwind v4 · HTMX · Alpine.js*
