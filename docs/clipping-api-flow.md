# Clipping API — Complete Execution Flow

> **Audience:** Frontend engineers building the Reelforge clipping UI.
> This document covers every state, every API call, every scenario — from job creation to analytics sync.
> All base URLs assume `/api/v1/`.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Model State Reference](#2-model-state-reference)
3. [Full Happy Path (No Gates)](#3-full-happy-path-no-gates)
4. [Gate Pause Scenario](#4-gate-pause-scenario)
5. [Failure & Retry Scenarios](#5-failure--retry-scenarios)
6. [Candidate Management Scenarios](#6-candidate-management-scenarios)
7. [Preview Workflows](#7-preview-workflows)
8. [Asset & Template Management](#8-asset--template-management)
9. [SSE Streaming Reference](#9-sse-streaming-reference)
10. [The 10-Stage Render Pipeline](#10-the-10-stage-render-pipeline)
11. [Complete API Surface Quick Reference](#11-complete-api-surface-quick-reference)

---

## 1. Overview

The Reelforge clipping feature takes a long-form video (YouTube URL, direct URL, or uploaded file) and automatically generates short-form social clips. The backend handles transcription, LLM-based candidate identification, and a 10-stage video render pipeline. The frontend drives the approval, configuration, and rendering workflow through a REST API with SSE for real-time updates.

### Phase Summary

| Phase | What Happens | Models Involved |
|-------|-------------|-----------------|
| **Creation** | Job created; source video download queued | `ClippingJob` |
| **Downloading** | Video downloaded via yt-dlp or HTTP | `ClippingJob` |
| **Transcription** | Audio extracted; sent to OpenAI Whisper | `ClippingJob` |
| **Analysis** | LLM generates clip candidates from transcript | `ClippingJob`, `ClipCandidate` |
| **Approval** | Operator reviews and approves/rejects candidates | `ClipCandidate` |
| **Configuration** | Layout, style, overlays edited per candidate | `ClipLayoutConfig`, `ClipStyleConfig`, `ClipTimedOverlay` |
| **Rendering** | 10-stage render pipeline processes each approved clip | `ClipRender`, `ClipRenderStageResult` |
| **Distribution** | Rendered clips posted to social platforms | `ClipPost` |
| **Analytics** | Post metrics synced from platforms | `ClipPost` |

---

## 2. Model State Reference

### 2a. ClippingJob States

`ClippingJob.status` is an FSM-protected field. Only the listed transitions are valid.

```
INITIALIZING
     │
     ▼
DOWNLOADING ──────────────────────────────────────────────┐
     │                                                     │
     ▼                                                     │
TRANSCRIBING ─────────────────────────────────────────────┤
     │                                                     │
     ▼                                                     ▼
ANALYZING ──────────────────────────────────────────── PAUSED
     │                                                     │
     ▼                                             ┌───────┴──────────┐
AWAITING_CLIP_APPROVAL ─────────────────────────── ▼                  ▼
     │                                    resume_to_approval   resume_to_rendering
     ▼
RENDERING ─────────────────────────────────────────────────┐
     │                                                      │
     ▼                                                      │
DISTRIBUTING                                                │
     │                                                      │
     ▼                                                      │
COMPLETED                                                   │
                                                            ▼
                                Any state → FAILED (mark_failed transition)
```

| Status | Description |
|--------|-------------|
| `INITIALIZING` | Job record created; no processing started yet |
| `DOWNLOADING` | Source video being fetched (yt-dlp or HTTP) |
| `TRANSCRIBING` | Audio extracted; Whisper API call in progress |
| `ANALYZING` | LLM analysis running; candidates being generated |
| `AWAITING_CLIP_APPROVAL` | Analysis complete; operator must review candidates |
| `RENDERING` | Approved candidates running through the render pipeline |
| `DISTRIBUTING` | Rendered clips being posted to social platforms |
| `COMPLETED` | All distribution complete |
| `FAILED` | A task failed after exhausting retries; `last_error` has details |
| `PAUSED` | Job manually paused; can resume to `AWAITING_CLIP_APPROVAL` or `RENDERING` |

**Key fields on ClippingJob:**
- `status` — current FSM state
- `last_error` — error message when `FAILED`
- `started_at` / `completed_at` / `failed_at` — timestamps
- `source_type` — `YOUTUBE_URL`, `DIRECT_URL`, or `UPLOAD`
- `transcript_text` / `transcript_json` — populated after transcription
- `analysis_manifest` — full JSON from the analysis stage

---

### 2b. ClipCandidate States

`ClipCandidate.status` is a plain CharField (not FSM-protected).

```
              PROPOSED
             /        \
            ▼          ▼
        APPROVED     REJECTED
            │            │
            │     undo-reject (→ PROPOSED)
            ▼
        RENDERING
            │
            ▼
        RENDERED
            │
            ▼
       DISTRIBUTING
            │
            ▼
       DISTRIBUTED
```

| Status | Description |
|--------|-------------|
| `PROPOSED` | Created by LLM analysis; awaiting operator decision |
| `APPROVED` | Operator approved; eligible for rendering |
| `REJECTED` | Operator rejected; excluded from rendering |
| `RENDERING` | `render_clip` task is running |
| `RENDERED` | Render pipeline completed successfully |
| `DISTRIBUTING` | `post_clip` task is posting to social platforms |
| `DISTRIBUTED` | All posts completed |

**Key fields on ClipCandidate:**
- `status` — current status
- `title` — editable clip title
- `hook_text` — text for the hook overlay
- `start_sec` / `end_sec` — clip time range in the source video
- `relevance_score` — LLM-assigned score (0.0–1.0)
- `render_gates` — `list[int]` of stage order numbers where render should pause (e.g. `[5, 8]`)
- `layout_config` — nested `ClipLayoutConfig` (auto-created on candidate creation)
- `style_config` — nested `ClipStyleConfig` (auto-created on candidate creation)

---

### 2c. ClipRender States

`ClipRender.status` is a plain CharField.

```
PENDING → RUNNING → COMPLETED
                  ↘ FAILED
                  ↘ PAUSED_AT_GATE → (resume) → RUNNING → COMPLETED
```

| Status | Description |
|--------|-------------|
| `PENDING` | Render record created; task not yet picked up |
| `RUNNING` | Pipeline actively processing stages |
| `COMPLETED` | All stages finished; `video_file` is populated |
| `FAILED` | A stage failed; `error_message` has details |
| `PAUSED_AT_GATE` | Pipeline paused at an operator review gate; `paused_at_stage` indicates where |

**Key fields on ClipRender:**
- `status` — current status
- `paused_at_stage` — integer (1–10); set when `PAUSED_AT_GATE`
- `video_file` — final video file; available when `COMPLETED`
- `file_size_bytes` — size of final output
- `stage_results` — array of `ClipRenderStageResult` objects (one per completed stage)
- `error_message` — set when `FAILED`

---

### 2d. ClipPost States

`ClipPost.status` is a plain CharField.

| Status | Description |
|--------|-------------|
| `PENDING` | Post record created; `post_clip` task not yet run |
| `POSTING` | `post_clip` task is actively uploading |
| `POSTED` | Successfully published; `platform_url` is populated |
| `SCHEDULED` | Scheduled for a future publish time |
| `FAILED` | Post failed after retries; `error_message` has details |

---

### 2e. ClipRenderStageResult States

One record per pipeline stage, per render attempt.

| Status | Description |
|--------|-------------|
| `PENDING` | Stage has not started yet |
| `RUNNING` | Stage is actively processing |
| `COMPLETED` | Stage finished; `output_file` is the path to its output |
| `FAILED` | Stage threw an exception |
| `SKIPPED` | Stage's `should_run()` returned False (e.g. no intro asset configured) |

---

## 3. Full Happy Path (No Gates)

This is the standard flow: create a job, wait for analysis, approve candidates, render, distribute.

---

### Step 1 — Create the Clipping Job

**Call:**
```
POST /api/v1/clipping/jobs/
```

**Request body (YouTube URL):**
```json
{
  "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "source_type": "YOUTUBE_URL",
  "title": "My Source Video"
}
```

**Request body (Direct URL):**
```json
{
  "source_url": "https://cdn.example.com/video.mp4",
  "source_type": "DIRECT_URL"
}
```

**Request body (Uploaded file):**
```
POST /api/v1/clipping/jobs/
Content-Type: multipart/form-data

source_type=UPLOAD
source_video_file=<binary>
```

**Response:** `ClippingJob` object with `status: "INITIALIZING"`

**What happens next (automatic):**
- Backend immediately queues the `download_source_video` Celery task
- Job transitions: `INITIALIZING` → `DOWNLOADING`
- No further frontend action needed to kick off the pipeline

---

### Step 2 — Track Job Progress (Poll or SSE)

The pipeline runs fully automatically after creation. The frontend must track progress.

**Option A — SSE (recommended for live UI):**
```
GET /api/v1/clipping/jobs/{job_id}/stream/
```
Open an `EventSource` connection. The server pushes events as each task completes.
See [Section 9 — SSE Streaming Reference](#9-sse-streaming-reference) for the full event list.

**Option B — REST polling:**
```
GET /api/v1/clipping/jobs/{job_id}/
```
Poll every 3–5 seconds. Watch the `status` field progress through:
```
DOWNLOADING → TRANSCRIBING → ANALYZING → AWAITING_CLIP_APPROVAL
```

**Terminal states that stop the pipeline:**
- `AWAITING_CLIP_APPROVAL` — analysis done; operator action required
- `FAILED` — something went wrong; see `last_error`

---

### Step 3 — Fetch Clip Candidates

Once `status === "AWAITING_CLIP_APPROVAL"`:

**Call:**
```
GET /api/v1/clipping/candidates/?job={job_id}
```

All candidates will have `status: "PROPOSED"`. Each candidate includes:
- `id` — candidate UUID
- `title` — suggested clip title
- `start_sec` / `end_sec` — time range
- `relevance_score` — LLM confidence (0.0–1.0)
- `hook_text` — suggested hook
- `layout_config.id` — ID for the auto-created layout config
- `style_config.id` — ID for the auto-created style config
- `render_gates` — currently `[]` (no gates by default)

---

### Step 4 — Approve or Reject Candidates

**Approve a single candidate:**
```
POST /api/v1/clipping/candidates/{candidate_id}/approve/
```
Response: updated candidate with `status: "APPROVED"`

**Reject a single candidate:**
```
POST /api/v1/clipping/candidates/{candidate_id}/reject/
```
Request body (optional):
```json
{ "reason": "Too much dead air in this segment" }
```

**Bulk approve all PROPOSED candidates on the job:**
```
POST /api/v1/clipping/jobs/{job_id}/approve-all/
```

---

### Step 5 — Configure Layout (Optional)

Each candidate has a `ClipLayoutConfig` auto-created at analysis time.
Fetch its ID from the candidate's `layout_config.id` field.

**Update layout config:**
```
PATCH /api/v1/clipping/layout-configs/{layout_config_id}/
```
```json
{
  "render_mode": "SMART_CROP",
  "crop_x": 0.1,
  "crop_y": 0.0,
  "crop_width": 0.8,
  "crop_height": 1.0
}
```

Render modes:
- `SMART_CROP` — speaker-aware auto-tracking crop (9:16)
- `CENTER_CROP` — static center 9:16 crop
- `SPATIAL_STACK` — two-region stack (e.g. speaker on top, slides on bottom)

**Reset crop to auto-detect:**
```
POST /api/v1/clipping/layout-configs/{layout_config_id}/reset-crop/
```

---

### Step 6 — Configure Style (Optional)

Each candidate has a `ClipStyleConfig` auto-created at analysis time.
Fetch its ID from the candidate's `style_config.id` field.

**Update style config:**
```
PATCH /api/v1/clipping/style-configs/{style_config_id}/
```
```json
{
  "caption_style": "WORD_BY_WORD",
  "caption_position": "BOTTOM",
  "caption_animation": "POP",
  "watermark_enabled": true,
  "watermark_text": "@myhandle",
  "watermark_position": "TOP_RIGHT",
  "music_enabled": true,
  "music_volume_db": -20,
  "hook_enabled": true,
  "hook_duration_sec": 3.0
}
```

**Apply a saved render template (seeds all style fields):**
```
POST /api/v1/clipping/style-configs/{style_config_id}/apply-template/
```
```json
{ "template_id": "{render_template_id}" }
```

---

### Step 7 — Add Timed Overlays (Optional)

```
POST /api/v1/clipping/overlays/
```
```json
{
  "candidate": "{candidate_id}",
  "text": "Subscribe for more!",
  "start_sec": 5.0,
  "end_sec": 8.0,
  "position_x": 0.5,
  "position_y": 0.85,
  "font_size": 32,
  "font_color": "#FFFFFF",
  "opacity": 0.9
}
```

Timestamps are in **final output time** (after intro/hook are prepended).

List overlays for a candidate:
```
GET /api/v1/clipping/overlays/?candidate={candidate_id}
```

Update or delete:
```
PATCH /api/v1/clipping/overlays/{overlay_id}/
DELETE /api/v1/clipping/overlays/{overlay_id}/
```

---

### Step 8 — Start Rendering

**Call:**
```
POST /api/v1/clipping/jobs/{job_id}/start-render/
```

This dispatches one `render_clip` Celery task per APPROVED candidate.

**What happens:**
- Job status → `RENDERING`
- Each candidate: `APPROVED` → `RENDERING`
- Each `ClipRender` record created with `status: "PENDING"` → immediately `RUNNING`

**Response:** updated `ClippingJob` object

---

### Step 9 — Track Render Progress

**Poll render status:**
```
GET /api/v1/clipping/renders/{render_id}/
```

Or list all renders for a candidate:
```
GET /api/v1/clipping/renders/?candidate={candidate_id}
```

The response includes `stage_results` — an array showing the status of each of the 10 pipeline stages:
```json
{
  "id": "...",
  "status": "RUNNING",
  "paused_at_stage": null,
  "stage_results": [
    { "stage_order": 1, "stage_name": "Trim and Crop", "status": "COMPLETED", "duration_sec": 12.4 },
    { "stage_order": 2, "stage_name": "Intro Concat", "status": "SKIPPED" },
    { "stage_order": 3, "stage_name": "Hook", "status": "RUNNING" },
    ...
  ]
}
```

**Terminal states:**
- `COMPLETED` — render done; candidate status → `RENDERED`
- `FAILED` — stage failed; see `error_message`
- `PAUSED_AT_GATE` — paused at a review gate; see [Section 4](#4-gate-pause-scenario)

SSE emits `render_complete` when a render finishes.

---

### Step 10 — Download the Rendered Video

```
GET /api/v1/clipping/renders/{render_id}/download/
```

Returns:
```json
{ "download_url": "https://..." }
```

The URL is a pre-signed link with a short TTL. Fetch it immediately before redirecting the user.

---

### Step 11 — Track Distribution

After a render completes, the `post_clip` Celery task is automatically dispatched.
A `ClipPost` record is created for each target social platform configured on the job.

**List posts for a render:**
```
GET /api/v1/clipping/posts/?render={render_id}
```

Watch the `status` field: `PENDING` → `POSTING` → `POSTED`

When `POSTED`, the response includes `platform_url` — the live link to the published clip.

Candidate status mirrors the post state: `RENDERED` → `DISTRIBUTING` → `DISTRIBUTED`

---

### Step 12 — Sync Analytics

After a post is live, fetch updated platform metrics:

```
POST /api/v1/clipping/posts/{post_id}/sync-analytics/
```

Then read updated metrics from the post:
```
GET /api/v1/clipping/posts/{post_id}/
```

Fields updated: `views`, `likes`, `comments`, `shares`, `revenue_est_usd`, `last_analytics_sync`

---

## 4. Gate Pause Scenario

Render gates let the operator pause the render pipeline at specific stages to review intermediate output before continuing.

### 4a. Configure Gates

Before starting the render, set `render_gates` on the candidate:

```
PATCH /api/v1/clipping/candidates/{candidate_id}/
```
```json
{
  "render_gates": [5, 8]
}
```

This means: **pause after stage 5 (Captions)** and **pause again after stage 8 (Progress Bar)**.
See [Section 10](#10-the-10-stage-render-pipeline) for the full list of stages and their order numbers.

Common gate strategies:
- `[5]` — Review captions before applying watermark/overlays
- `[3, 5]` — Review hook text, then captions
- `[1]` — Review initial crop before any overlays are added

---

### 4b. First Gate Pause

After `POST /api/v1/clipping/jobs/{job_id}/start-render/`:

1. Render runs stages 1–5 normally
2. After stage 5 completes, pipeline raises `GatePausedException`
3. Render status → `PAUSED_AT_GATE`, `paused_at_stage: 5`
4. SSE emits `render_paused` event with `{ "render_id": "...", "paused_at_stage": 5 }`

**Poll to detect the pause:**
```
GET /api/v1/clipping/renders/{render_id}/
```
```json
{
  "status": "PAUSED_AT_GATE",
  "paused_at_stage": 5,
  "stage_results": [
    { "stage_order": 1, "status": "COMPLETED" },
    ...
    { "stage_order": 5, "status": "COMPLETED" },
    { "stage_order": 6, "status": "PENDING" },
    ...
  ]
}
```

---

### 4c. Operator Review

While paused, the operator can:

- View the stage 5 output (caption file path in `stage_results[4].output_file`)
- Modify the style config if captions need changes:
  ```
  PATCH /api/v1/clipping/style-configs/{style_config_id}/
  { "caption_style": "CHUNKED", "caption_position": "CENTER" }
  ```

If style config is changed, the operator should **rerun from stage 5** instead of resuming (to re-generate captions with the new settings). See [Section 5b](#5b-render-failure) for the rerun endpoint.

---

### 4d. Resume After Gate

If no changes needed, resume from the next stage:

```
POST /api/v1/clipping/renders/{render_id}/resume/
```

**What happens:**
- Pipeline continues from stage 6 (Watermark) using stage 5's output as input
- Render status → `RUNNING`
- Runs stages 6, 7, 8 — then pauses again at stage 8 (`render_gates: [5, 8]`)

---

### 4e. Second Gate Pause and Final Resume

Same pattern: `PAUSED_AT_GATE` with `paused_at_stage: 8`.
Operator reviews the progress-bar stage output, then:

```
POST /api/v1/clipping/renders/{render_id}/resume/
```

Pipeline runs stages 9 (Outro) and 10 (Music Mix), then → `COMPLETED`.

---

### Gate Pause Flow Diagram

```
start-render
     │
     ▼
Stage 1: Trim & Crop ──── COMPLETED
Stage 2: Intro Concat ─── SKIPPED (no intro)
Stage 3: Hook ─────────── COMPLETED
Stage 4: Caption Trans ─── SKIPPED (no translation)
Stage 5: Captions ──────── COMPLETED
     │
     ▼
 PAUSED_AT_GATE (stage 5)
     │
   resume/
     │
     ▼
Stage 6: Watermark ─────── COMPLETED
Stage 7: Timed Overlays ─── COMPLETED
Stage 8: Progress Bar ───── COMPLETED
     │
     ▼
 PAUSED_AT_GATE (stage 8)
     │
   resume/
     │
     ▼
Stage 9: Outro Concat ───── COMPLETED
Stage 10: Music Mix ──────── COMPLETED
     │
     ▼
  COMPLETED
```

---

## 5. Failure & Retry Scenarios

### 5a. Job-Level Failure (Download / Transcription / Analysis)

If `download_source_video`, `transcribe_video`, or `analyze_clips` fails after exhausting retries:

- Job status → `FAILED`
- `job.last_error` contains the error message
- `job.failed_at` contains the failure timestamp

**To retry:**
```
POST /api/v1/clipping/jobs/{job_id}/retry/
```

The backend decides where to resume:
- If the job failed during or after `TRANSCRIBING` → retries from `transcribe_video`
- If the job failed during or after `ANALYZING` → retries from `analyze_clips`

After calling retry, poll `status` again — it will transition back through the pipeline states.

---

### 5b. Render Failure

If a render stage throws an exception:

- `ClipRender.status` → `FAILED`
- `ClipRender.error_message` contains the error
- The failed stage in `stage_results` has `status: "FAILED"`

**Option 1 — Rerun from a specific stage:**
```
POST /api/v1/clipping/renders/{render_id}/rerun/{stage_order}/
```

Examples:
- `/rerun/1/` — restart the entire render from scratch
- `/rerun/5/` — re-run captions and everything after (e.g. after fixing style config)
- `/rerun/10/` — re-run only the final music mix

This deletes stage results from `stage_order` onwards and re-dispatches the `render_clip` task starting from that stage.

**Option 2 — Rerun after fixing style config:**
If captions are wrong, update the style config first, then rerun from stage 5:
```
PATCH /api/v1/clipping/style-configs/{style_config_id}/
{ "caption_style": "LOWER_THIRD" }

POST /api/v1/clipping/renders/{render_id}/rerun/5/
```

---

### 5c. Post Failure

If `post_clip` fails (network issue, platform auth expired, etc.):

- `ClipPost.status` → `FAILED`
- `ClipPost.error_message` contains platform-specific details

The Celery task retries automatically up to 3 times with 120-second delays.
There is no manual retry endpoint — fix the platform auth issue and the next Celery retry will succeed.

---

## 6. Candidate Management Scenarios

### 6a. Reject a Candidate

```
POST /api/v1/clipping/candidates/{candidate_id}/reject/
```
```json
{ "reason": "Too slow, no value" }
```

Candidate status → `REJECTED`. Rejected candidates are excluded from `start-render`.

---

### 6b. Undo a Rejection

```
POST /api/v1/clipping/candidates/{candidate_id}/undo-reject/
```

Candidate status → `PROPOSED`. The candidate is back in the review queue.

---

### 6c. Edit Candidate Fields

```
PATCH /api/v1/clipping/candidates/{candidate_id}/
```
```json
{
  "title": "Updated clip title",
  "hook_text": "You won't believe what happens next...",
  "render_gates": [5]
}
```

Editable fields: `title`, `hook_text`, `render_gates`.
Time range (`start_sec`, `end_sec`) and `relevance_score` are set by the LLM and not editable via PATCH.

---

### 6d. Filter Candidates by Status

```
GET /api/v1/clipping/candidates/?job={job_id}&status=APPROVED
GET /api/v1/clipping/candidates/?job={job_id}&status=PROPOSED
GET /api/v1/clipping/candidates/?job={job_id}&status=RENDERED
```

Valid status values: `PROPOSED`, `APPROVED`, `REJECTED`, `RENDERING`, `RENDERED`, `DISTRIBUTING`, `DISTRIBUTED`

---

## 7. Preview Workflows

Before starting a full render, the operator can generate a preview image to verify layout crop regions or caption/watermark styles.

### 7a. Layout Preview

Shows a single frame with crop region overlays drawn on it.
- For `SMART_CROP` / `CENTER_CROP`: green rectangle showing the 9:16 crop window
- For `SPATIAL_STACK`: green (region A) and blue (region B) rectangles

**Step 1 — Configure the layout:**
```
PATCH /api/v1/clipping/layout-configs/{layout_config_id}/
{ "render_mode": "SPATIAL_STACK", ... }
```

**Step 2 — Queue the preview:**
```
POST /api/v1/clipping/candidates/{candidate_id}/trigger-preview/
```

This queues the `preview_clip_layout` task (completes in ~10–120 seconds).

**Step 3 — Poll for completion:**
```
GET /api/v1/clipping/candidates/{candidate_id}/preview-status/
```
```json
{ "ready": true, "preview_url": "https://..." }
```

Poll every 2–3 seconds until `ready: true`.

---

### 7b. Style Preview

Shows a frame with the configured caption and watermark rendered over it — useful for checking font, color, and positioning before a full render.

Same endpoints as layout preview — `trigger-preview` and `preview-status` — but internally uses the `preview_clip_layout` task which reads `style_config` settings.

> Note: Modifying `layout_config` triggers a layout preview; modifying `style_config` also uses the same `trigger-preview` action. The preview reflects the most recently saved config state.

---

## 8. Asset & Template Management

These resources are global (not per-job) and can be managed independently.

### 8a. Intro / Outro Video Assets

**Upload:**
```
POST /api/v1/clipping/media-assets/
Content-Type: multipart/form-data

asset_type=INTRO
file=<binary>
label=My Intro
```

**List:**
```
GET /api/v1/clipping/media-assets/?asset_type=INTRO
GET /api/v1/clipping/media-assets/?asset_type=OUTRO
```

**Get playback URL:**
```
GET /api/v1/clipping/media-assets/{asset_id}/preview-url/
```
Returns `{ "url": "https://..." }`

**Assign to a clip's style config:**
```
PATCH /api/v1/clipping/style-configs/{style_config_id}/
{
  "intro_enabled": true,
  "intro_asset": "{asset_id}",
  "outro_enabled": true,
  "outro_asset": "{asset_id}"
}
```

---

### 8b. Background Music Assets

**Upload:**
```
POST /api/v1/clipping/music-assets/
Content-Type: multipart/form-data

file=<binary>
label=Lo-fi Chill Beat
```

**List:**
```
GET /api/v1/clipping/music-assets/
```

**Get playback URL:**
```
GET /api/v1/clipping/music-assets/{asset_id}/preview-url/
```

**Assign to a clip's style config:**
```
PATCH /api/v1/clipping/style-configs/{style_config_id}/
{
  "music_enabled": true,
  "music_asset": "{asset_id}",
  "music_volume_db": -18,
  "music_fade_in_sec": 1.0,
  "music_fade_out_sec": 2.0
}
```

---

### 8c. Render Templates

Templates save a full style configuration that can be re-applied to any candidate.

**List templates:**
```
GET /api/v1/clipping/render-templates/
```

**Create a template:**
```
POST /api/v1/clipping/render-templates/
{
  "name": "TikTok Default",
  "caption_style": "WORD_BY_WORD",
  "caption_position": "BOTTOM",
  "watermark_enabled": true,
  "watermark_text": "@mybrand",
  ...
}
```

**Set as default (auto-applied to new candidates):**
```
POST /api/v1/clipping/render-templates/{template_id}/set-default/
```

**Apply template to a candidate's style config:**
```
POST /api/v1/clipping/style-configs/{style_config_id}/apply-template/
{ "template_id": "{template_id}" }
```

This overwrites all style fields with the template's values.

---

## 9. SSE Streaming Reference

Connect to the SSE stream to receive real-time updates without polling:

```javascript
const source = new EventSource(`/api/v1/clipping/jobs/${jobId}/stream/`);

source.addEventListener('analysis_complete', (e) => {
  const data = JSON.parse(e.data);
  // { job_id, candidate_count }
});

source.addEventListener('render_complete', (e) => {
  const data = JSON.parse(e.data);
  // { render_id, candidate_id }
});
```

### Event Reference

| Event | When It Fires | Payload Fields |
|-------|--------------|----------------|
| `analysis_complete` | `analyze_clips` task finishes; candidates created | `job_id`, `candidate_count` |
| `render_started` | `render_clip` task begins processing a candidate | `render_id`, `candidate_id` |
| `stage_complete` | Each render stage finishes successfully | `render_id`, `stage_order`, `stage_name`, `duration_sec` |
| `render_paused` | Pipeline hits a gate and pauses | `render_id`, `paused_at_stage` |
| `render_complete` | Render pipeline finishes all stages | `render_id`, `candidate_id` |
| `post_complete` | `post_clip` task publishes a clip to a platform | `post_id`, `platform`, `platform_url` |

### Fallback Strategy

SSE connections can drop (network interruption, server restart). The frontend must implement a REST fallback:

1. Open SSE connection on job load
2. On `error` or `close` event: switch to polling `GET /api/v1/clipping/jobs/{id}/` every 5 seconds
3. On reconnect: resume SSE and discard the polling interval

---

## 10. The 10-Stage Render Pipeline

Each approved candidate runs through all 10 stages in order. Stages that are not applicable are `SKIPPED` automatically.

| Order | Stage Name | Purpose | Skipped When |
|-------|-----------|---------|-------------|
| 1 | **Trim and Crop** | Extracts the clip segment (`start_sec`–`end_sec`); applies layout-specific crop to 9:16. Smart Crop: speaker-tracking. Spatial Stack: two-region composite. Center Crop: static center. | Never skipped |
| 2 | **Intro Concat** | Prepends the intro asset video to the clip | `intro_enabled: false` or no intro asset assigned |
| 3 | **Hook** | Renders hook text overlay at the beginning of the clip (title card or overlay) | `hook_enabled: false` or `hook_text` is empty |
| 4 | **Caption Translation** | Translates the transcript to the target language | `caption_translate_to` is null/empty |
| 5 | **Captions** | Burns subtitles into the video using libass. Supports Word-by-Word, Chunked, Lower Third, Emoji Accent styles | `captions_enabled: false` |
| 6 | **Watermark** | Overlays image or text watermark at configured position and opacity | `watermark_enabled: false` |
| 7 | **Timed Overlays** | Applies all `ClipTimedOverlay` records — time-ranged text/image overlays | No `ClipTimedOverlay` records exist for this candidate |
| 8 | **Progress Bar** | Renders a progress bar (top or bottom) that fills as the video plays | `progress_bar_enabled: false` |
| 9 | **Outro Concat** | Appends the outro asset video | `outro_enabled: false` or no outro asset assigned |
| 10 | **Music Mix** | Final audio mix: blends original audio with background music track at configured volume; applies fade in/out | `music_enabled: false` or no music asset assigned |

**Important:** Timed overlay timestamps (`start_sec`, `end_sec` on `ClipTimedOverlay`) are in **final output time** — after intro and hook are prepended. Account for intro duration + hook duration when setting overlay times.

---

## 11. Complete API Surface Quick Reference

### ClippingJob Endpoints

| Method | Endpoint | When to Use | State Change |
|--------|----------|------------|-------------|
| `POST` | `/clipping/jobs/` | Create a new clipping job | Creates `INITIALIZING` → auto `DOWNLOADING` |
| `GET` | `/clipping/jobs/` | List all jobs | — |
| `GET` | `/clipping/jobs/{id}/` | Poll job status + see candidates | — |
| `PATCH` | `/clipping/jobs/{id}/` | Update job metadata | — |
| `DELETE` | `/clipping/jobs/{id}/` | Delete a job | — |
| `POST` | `/clipping/jobs/{id}/start-render/` | Kick off rendering for all APPROVED candidates | Job → `RENDERING` |
| `POST` | `/clipping/jobs/{id}/approve-all/` | Bulk-approve all PROPOSED candidates | All candidates → `APPROVED` |
| `POST` | `/clipping/jobs/{id}/retry/` | Retry a FAILED job from transcription or analysis | Job → `TRANSCRIBING` or `ANALYZING` |
| `GET` | `/clipping/jobs/{id}/stream/` | Open SSE stream for real-time events | — |

### ClipCandidate Endpoints

| Method | Endpoint | When to Use | State Change |
|--------|----------|------------|-------------|
| `GET` | `/clipping/candidates/?job={id}` | List candidates for a job | — |
| `GET` | `/clipping/candidates/?job={id}&status=PROPOSED` | Filter by status | — |
| `GET` | `/clipping/candidates/{id}/` | Get full candidate detail (includes layout/style config IDs) | — |
| `PATCH` | `/clipping/candidates/{id}/` | Edit title, hook_text, render_gates | — |
| `POST` | `/clipping/candidates/{id}/approve/` | Approve a candidate for rendering | → `APPROVED` |
| `POST` | `/clipping/candidates/{id}/reject/` | Reject a candidate | → `REJECTED` |
| `POST` | `/clipping/candidates/{id}/undo-reject/` | Undo a rejection | → `PROPOSED` |
| `POST` | `/clipping/candidates/{id}/trigger-preview/` | Queue a layout/style preview image | — |
| `GET` | `/clipping/candidates/{id}/preview-status/` | Check if preview image is ready | — |

### ClipLayoutConfig Endpoints

| Method | Endpoint | When to Use | State Change |
|--------|----------|------------|-------------|
| `GET` | `/clipping/layout-configs/{id}/` | Get current layout settings | — |
| `PATCH` | `/clipping/layout-configs/{id}/` | Update crop mode and coordinates | — |
| `POST` | `/clipping/layout-configs/{id}/reset-crop/` | Clear manual crop coordinates | — |

### ClipStyleConfig Endpoints

| Method | Endpoint | When to Use | State Change |
|--------|----------|------------|-------------|
| `GET` | `/clipping/style-configs/{id}/` | Get current style settings | — |
| `PATCH` | `/clipping/style-configs/{id}/` | Update captions, watermark, music, hook, etc. | — |
| `POST` | `/clipping/style-configs/{id}/apply-template/` | Seed all style fields from a render template | — |

### ClipRender Endpoints

| Method | Endpoint | When to Use | State Change |
|--------|----------|------------|-------------|
| `GET` | `/clipping/renders/?candidate={id}` | List renders for a candidate | — |
| `GET` | `/clipping/renders/{id}/` | Poll render status + stage results | — |
| `POST` | `/clipping/renders/{id}/resume/` | Resume a PAUSED_AT_GATE render | → `RUNNING` |
| `POST` | `/clipping/renders/{id}/rerun/{stage_order}/` | Rerun from a specific stage (1–10) | → `RUNNING` |
| `GET` | `/clipping/renders/{id}/download/` | Get pre-signed download URL for final video | — |

### ClipTimedOverlay Endpoints

| Method | Endpoint | When to Use | State Change |
|--------|----------|------------|-------------|
| `GET` | `/clipping/overlays/?candidate={id}` | List overlays for a candidate | — |
| `POST` | `/clipping/overlays/` | Add a timed overlay | — |
| `GET` | `/clipping/overlays/{id}/` | Get overlay details | — |
| `PATCH` | `/clipping/overlays/{id}/` | Update overlay text/timing/position | — |
| `DELETE` | `/clipping/overlays/{id}/` | Remove an overlay | — |

### ClipMediaAsset Endpoints

| Method | Endpoint | When to Use | State Change |
|--------|----------|------------|-------------|
| `GET` | `/clipping/media-assets/?asset_type=INTRO` | List intro assets | — |
| `GET` | `/clipping/media-assets/?asset_type=OUTRO` | List outro assets | — |
| `POST` | `/clipping/media-assets/` | Upload a new intro or outro asset | — |
| `PATCH` | `/clipping/media-assets/{id}/` | Update asset metadata | — |
| `DELETE` | `/clipping/media-assets/{id}/` | Delete an asset | — |
| `GET` | `/clipping/media-assets/{id}/preview-url/` | Get playback URL | — |

### ClipMusicAsset Endpoints

| Method | Endpoint | When to Use | State Change |
|--------|----------|------------|-------------|
| `GET` | `/clipping/music-assets/` | List music assets | — |
| `POST` | `/clipping/music-assets/` | Upload a new music track | — |
| `PATCH` | `/clipping/music-assets/{id}/` | Update asset metadata | — |
| `DELETE` | `/clipping/music-assets/{id}/` | Delete an asset | — |
| `GET` | `/clipping/music-assets/{id}/preview-url/` | Get playback URL | — |

### ClipRenderTemplate Endpoints

| Method | Endpoint | When to Use | State Change |
|--------|----------|------------|-------------|
| `GET` | `/clipping/render-templates/` | List all templates | — |
| `POST` | `/clipping/render-templates/` | Create a new template | — |
| `PATCH` | `/clipping/render-templates/{id}/` | Update template fields | — |
| `DELETE` | `/clipping/render-templates/{id}/` | Delete (blocked if `is_default: true`) | — |
| `POST` | `/clipping/render-templates/{id}/set-default/` | Set as the default template | — |

### ClipPost Endpoints

| Method | Endpoint | When to Use | State Change |
|--------|----------|------------|-------------|
| `GET` | `/clipping/posts/?render={id}` | List posts for a render | — |
| `GET` | `/clipping/posts/{id}/` | Get post status + platform URL | — |
| `POST` | `/clipping/posts/{id}/sync-analytics/` | Queue analytics sync for a posted clip | — |

---

*Last updated: 2026-05-03 — reflects the API-based clipping implementation*
