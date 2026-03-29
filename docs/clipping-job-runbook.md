# Clipping Job Runbook — QA & UAT Guide

> **Audience:** QA engineers and UAT participants running end-to-end clipping tests.
> This document covers every step, every button, every status, and every recovery action.

---

## Table of Contents

1. [Prerequisites & Setup](#1-prerequisites--setup)
2. [System Overview — The Pipeline](#2-system-overview--the-pipeline)
3. [Step 1 — Create a Clipping Job](#3-step-1--create-a-clipping-job)
4. [Step 2 — Start the Job (Download)](#4-step-2--start-the-job-download)
5. [Step 3 — Transcription](#5-step-3--transcription)
6. [Step 4 — Clip Analysis](#6-step-4--clip-analysis)
7. [Step 5 — Clip Candidate Review & Approval](#7-step-5--clip-candidate-review--approval)
8. [Step 6 — Rendering](#8-step-6--rendering)
9. [Step 7 — Inspecting Render Stages](#9-step-7--inspecting-render-stages)
10. [Step 8 — Distribution](#10-step-8--distribution)
11. [Retry & Recovery Reference](#11-retry--recovery-reference)
12. [Status Badge Reference](#12-status-badge-reference)
13. [Auto-Created Records Reference](#13-auto-created-records-reference)
14. [Common Failure Scenarios & Fixes](#14-common-failure-scenarios--fixes)

---

## 1. Prerequisites & Setup

Before starting a QA run, confirm the following are in place:

### Services running

```bash
just up          # Start all Docker services
just logs        # Confirm no crash-loop restarts
```

All of these must be healthy:
- `django` — Django app (port 8000)
- `***REMOVED***` — Database
- `redis` — Celery broker
- `celeryworker` — Processes all clipping tasks
- `celerybeat` — Scheduler (not required for manual QA runs)

### Admin access

Navigate to `http://localhost:8000/admin/` and log in with a superuser account.

### Channel configured

A `Channel` must exist with at minimum:
- **Name** and **slug** set
- **Default render mode** set (`SMART_CROP`, `SPATIAL_STACK`, or `CENTER_CROP`)
- A `ClipRenderTemplate` auto-created (see [Section 13](#13-auto-created-records-reference))

To verify: go to **Channels → Channels**, open a channel, and confirm a **Clip Render Template** inline is visible at the bottom.

### Test video

Have a YouTube URL or direct video URL ready. Minimum recommended length: 5 minutes. The system will extract the best clips from this source video.

---

## 2. System Overview — The Pipeline

A Clipping Job moves through 9 FSM states, triggering Celery tasks at each transition:

```
INITIALIZING
     │
     │  [Action: "Start clipping job (begin download)"]
     ▼
DOWNLOADING        ← download_clip_source task
     │               Downloads video via yt-dlp or direct URL
     ▼
TRANSCRIBING       ← transcribe_clip task
     │               Whisper transcription (word-level timestamps)
     ▼
ANALYZING          ← analyze_clips task
     │               LLM identifies best clip segments
     ▼
AWAITING_CLIP_APPROVAL
     │
     │  [Action: "Approve selected candidates"]
     ▼
RENDERING          ← render_clip task (one per approved candidate)
     │               10-stage FFmpeg pipeline per candidate
     ▼
DISTRIBUTING       ← post_clip task (one per render + target account)
     │               Uploads to YouTube / TikTok / Instagram
     ▼
COMPLETED
```

**FAILED** and **PAUSED** are reachable from most states. See [Section 11](#11-retry--recovery-reference) for recovery.

---

## 3. Step 1 — Create a Clipping Job

**Navigate to:** Admin → Clipping → Clipping Jobs → **+ Add Clipping Job** (top right)

### Fields to fill in

| Field | Description | Example |
|---|---|---|
| **Channel** | The channel this job belongs to | `My Tech Channel` |
| **Source type** | `YouTube URL`, `Direct URL`, or `File Upload` | `YouTube URL` |
| **Source URL** | The video URL (if not a file upload) | `https://youtube.com/watch?v=...` |
| **Source video file** | Upload an MP4 directly (if Source type = File Upload) | — |
| **Clips requested** | How many clip candidates the AI should find | `5` (default) |
| **Target accounts** | Social accounts to distribute to (optional at creation) | — |

> **Note:** Leave all other fields blank — they are populated automatically by the pipeline.

### Save

Click **Save** (bottom right of the form).

**Expected result:** A new Clipping Job is created with status badge **Initializing** (grey).

The following records are auto-created immediately on save:
- Nothing yet — auto-records are created as candidates are found (see [Section 13](#13-auto-created-records-reference))

---

## 4. Step 2 — Start the Job (Download)

The job will not start automatically from `INITIALIZING`. You must trigger it manually.

**Navigate to:** Admin → Clipping → Clipping Jobs → (select your job's checkbox)

### Action

1. Select the checkbox next to your Clipping Job
2. In the **Action** dropdown (top of the list), select **"Start clipping job (begin download)"**
3. Click **Go**

**Expected result:**
- Status changes from **Initializing** (grey) → **Downloading** (blue)
- A Celery task `download_clip_source` is queued
- The `downloaded_file` field on the job is populated once the task completes
- Status automatically advances to **Transcribing** (blue) upon success

> **Validation:** The action checks that the job is in `INITIALIZING` state. If you select a job in any other state, it will be skipped and a warning shown: *"Skipped N job(s) — not in INITIALIZING state."*

---

## 5. Step 3 — Transcription

Transcription runs automatically after download completes. No manual action required.

**Celery task:** `transcribe_clip`

**What it does:**
- Calls the configured transcription provider (Whisper)
- Populates `transcript_text` and `transcript_json` (with word-level timestamps) on the job
- Records `transcription_provider` and `transcription_cost_usd`

**Expected result:** Status advances from **Transcribing** → **Analyzing** automatically.

### If transcription gets stuck

From the Clipping Jobs list:
1. Select the stuck job
2. Action: **"Retry transcription for stuck/failed jobs"** → **Go**

This action works for jobs in `TRANSCRIBING` or `FAILED` state. It re-queues the `transcribe_clip` task.

---

## 6. Step 4 — Clip Analysis

Analysis runs automatically after transcription. No manual action required.

**Celery task:** `analyze_clips`

**What it does:**
- Sends the transcript to an LLM (via the channel's provider)
- The LLM identifies the N best clip segments (based on `clips_requested`)
- Creates one `ClipCandidate` record per identified clip
- Each candidate gets a `ClipLayoutConfig` and `ClipStyleConfig` auto-created (see [Section 13](#13-auto-created-records-reference))

**Expected result:** Status advances from **Analyzing** → **Awaiting Clip Approval** automatically.

### Verifying candidates were created

**Navigate to:** Admin → Clipping → Clip Candidates

You should see N new candidates, each linked to your Clipping Job, all with status **Proposed**.

Each candidate has:
- `start_sec` / `end_sec` — the clip time range in the source video
- `title` — AI-generated clip title
- `hook` — AI-generated hook text
- `score` — relevance/quality score from the LLM
- A **Layout Config** inline with `render_mode` pre-populated from channel defaults
- A **Style Config** inline with caption/watermark settings pre-populated from the channel's `ClipRenderTemplate`

---

## 7. Step 5 — Clip Candidate Review & Approval

The job is now paused waiting for operator approval of candidates.

**Navigate to:** Admin → Clipping → Clipping Jobs → open your job

### Review candidates

Scroll to the **Clip Candidates** section (inline on the job detail page). You'll see all proposed candidates with their title, score, start/end times, and render mode.

To view full detail on a candidate: click its title or navigate to Admin → Clipping → Clip Candidates → open the candidate.

### Optional: Generate a layout preview

Before approving, you can preview how a candidate will be cropped:

1. Go to Admin → Clipping → Clip Candidates
2. Select one or more candidates
3. Action: **"Generate layout preview image"** → **Go**
   - This runs `preview_clip_layout` task and populates the layout config's preview thumbnail
4. Action: **"Generate style preview image"** → **Go**
   - This runs `preview_clip_style` task and generates a style/caption preview image

### Approve candidates

From the **Clipping Jobs** list:
1. Select your job
2. Action: **"Approve selected candidates"** → **Go**

This approves all **Proposed** candidates on the selected job(s) — their status changes to **Approved**.

> **Alternatively:** approve individual candidates from the Clip Candidates list by selecting them and using the same action.

**Expected result on the job:** Status transitions from **Awaiting Clip Approval** → **Rendering** (blue).

---

## 8. Step 6 — Rendering

Rendering starts automatically when the job enters `RENDERING` state.

**Celery task:** `render_clip` — one task is queued **per approved candidate**

### What the render pipeline does

Each candidate goes through a 10-stage FFmpeg pipeline (see [Section 9](#9-step-7--inspecting-render-stages) for full stage details). A `ClipRender` record tracks the overall render status. A `ClipRenderStageResult` record is created for each stage that runs.

**Navigate to:** Admin → Clipping → Clip Renders

You should see one `ClipRender` per approved candidate, each starting in **Pending** status.

As the pipeline runs, status progresses:
- **Pending** (grey) → **Rendering** (blue) → **Completed** (green)
- On failure: → **Failed** (red)

### Triggering rendering manually

If rendering was not triggered automatically (e.g. you approved candidates while the job was paused):

From the Clipping Jobs list:
1. Select the job
2. Action: **"Trigger rendering for approved candidates"** → **Go**

This queues a `render_clip` task for every approved candidate that doesn't already have a running or completed render.

---

## 9. Step 7 — Inspecting Render Stages

Every render stage produces a `ClipRenderStageResult` record. These are visible as an inline on each `ClipRender`.

**Navigate to:** Admin → Clipping → Clip Renders → open a render

Scroll to the **Stage Results** inline. You'll see one row per stage that ran.

### The 10 render stages

| # | Stage name | What it does | Skipped when |
|---|---|---|---|
| 1 | `trim_and_crop` | Trims the source video to the clip's start/end seconds; applies smart crop, spatial stack (side-by-side), or center crop | Never (always runs) |
| 2 | `intro_concat` | Concatenates a media asset intro clip before the main clip | No `INTRO` asset configured on channel |
| 3 | `hook` | Burns a hook title card or overlay text onto the first few seconds | `hook_enabled = False` on style config |
| 4 | `caption_translation` | Translates the Whisper transcript via LLM to a target language | `caption_translate_to` is blank |
| 5 | `captions` | Generates ASS subtitle file and burns captions into the video | `caption_enabled = False` or no transcript |
| 6 | `watermark` | Burns a text or image watermark onto the video | `watermark_enabled = False` |
| 7 | `timed_overlays` | Burns timed text/image overlays at specific timestamps | No `ClipTimedOverlay` records on candidate |
| 8 | `progress_bar` | Draws a progress bar at the bottom of the frame | `progress_bar_enabled = False` |
| 9 | `outro_concat` | Concatenates a media asset outro clip after the main clip | No `OUTRO` asset configured on channel |
| 10 | `music_mix` | Mixes background music (from `ClipMusicAsset`) under the video audio | No `ClipMusicAsset` assigned to candidate |

### Stage result fields

Each `ClipRenderStageResult` shows:
- **Stage order** — number 1–10
- **Stage name** — e.g. `trim_and_crop`
- **Status** — Pending / Running / Completed / Skipped / Failed (see [Section 12](#12-status-badge-reference))
- **Duration** — how long the stage took in seconds
- **Error** — populated if the stage failed
- **Output** — link/path to the intermediate video file produced by this stage

---

## 10. Step 8 — Distribution

Distribution runs automatically when all renders for a job complete.

**Celery task:** `post_clip` — one task per `ClipRender` × `target account`

A `ClipPost` record tracks each distribution attempt.

**Navigate to:** Admin → Clipping → Clip Posts

| Field | Description |
|---|---|
| **Render** | Which `ClipRender` this post is for |
| **Account** | The `SocialAccount` it's being posted to |
| **Platform** | YouTube / TikTok / Instagram (badge) |
| **Status** | Pending → Posting → Posted (or Failed / Scheduled) |
| **External URL** | The live URL of the post once uploaded |
| **Scheduled for** | If posting is deferred |

**Expected result on job:** Once all posts complete, the job transitions from **Distributing** → **Completed** (green).

---

## 11. Retry & Recovery Reference

### Clipping Job actions (Admin → Clipping → Clipping Jobs)

| Action button text | When to use | What it does |
|---|---|---|
| **"Start clipping job (begin download)"** | Job is in `INITIALIZING` | Queues `download_clip_source` task |
| **"Retry transcription for stuck/failed jobs"** | Job is in `TRANSCRIBING` or `FAILED` | Re-queues `transcribe_clip` |
| **"Approve selected candidates"** | Job is in `AWAITING_CLIP_APPROVAL` | Marks all proposed candidates as Approved, transitions job to RENDERING |
| **"Trigger rendering for approved candidates"** | Job is in `RENDERING` or `PAUSED` but renders haven't started | Queues `render_clip` for each approved candidate |

### Clip Render actions (Admin → Clipping → Clip Renders)

| Action button text | When to use | What it does |
|---|---|---|
| **"Retry full render (from stage 1)"** | Render failed; want to start over | Deletes all stage results, resets render to `PENDING`, re-queues `render_clip` from stage 1 |
| **"Retry from stage 2 (skip trim/crop)"** | Stage 1 succeeded but a later stage failed; trim/crop output exists | Deletes stage results from stage 2 onward, re-queues starting at stage 2 |
| **"Retry from captions (stage 4)"** | Caption translation or caption burn failed; earlier stages are fine | Deletes stage results from stage 4 onward, re-queues starting at stage 4 |
| **"Clear stage outputs and reset to PENDING"** | Want to clear all state without re-queuing | Deletes all stage results, resets render to `PENDING` — no task queued |

### Clip Candidate actions (Admin → Clipping → Clip Candidates)

| Action button text | When to use | What it does |
|---|---|---|
| **"Generate layout preview image"** | Before rendering; want to verify crop/layout | Queues `preview_clip_layout` task — populates layout preview thumbnail |
| **"Generate style preview image"** | Before rendering; want to verify caption/style | Queues `preview_clip_style` task — generates style preview image |

---

## 12. Status Badge Reference

### Clipping Job status

| Status | Badge colour | Meaning |
|---|---|---|
| `INITIALIZING` | Grey | Job created; not started yet |
| `DOWNLOADING` | Blue | Source video being downloaded |
| `TRANSCRIBING` | Blue | Whisper transcription in progress |
| `ANALYZING` | Blue | LLM clip analysis in progress |
| `AWAITING_CLIP_APPROVAL` | Yellow/orange | Waiting for operator to approve candidates |
| `RENDERING` | Blue | One or more candidates rendering |
| `DISTRIBUTING` | Blue | Posting clips to social accounts |
| `COMPLETED` | Green | All stages complete |
| `FAILED` | Red | A task failed beyond its retry limit |
| `PAUSED` | Yellow/orange | Manually paused by operator |

### Clip Render status

| Status | Badge colour | Meaning |
|---|---|---|
| `PENDING` | Grey | Queued but not yet started |
| `RENDERING` | Blue | Pipeline actively running |
| `COMPLETED` | Green | All stages finished successfully |
| `FAILED` | Red | Pipeline aborted due to stage failure |

### Clip Render Stage Result status

| Status | Badge colour | Meaning |
|---|---|---|
| `PENDING` | Grey | Not yet run |
| `RUNNING` | Blue | Currently executing |
| `COMPLETED` | Green | Finished successfully |
| `SKIPPED` | Yellow/orange | `should_run()` returned False (configured off or no assets) |
| `FAILED` | Red | Stage raised an exception |

### Clip Candidate status

| Status | Badge colour | Meaning |
|---|---|---|
| `PROPOSED` | Grey | Newly created by analysis; awaiting review |
| `APPROVED` | Green | Approved by operator; ready to render |
| `REJECTED` | Grey | Rejected by operator; will not render |
| `RENDERING` | Blue | Render in progress |
| `RENDERED` | Green | Render completed successfully |
| `DISTRIBUTED` | Green | Posted to at least one social account |

### Clip Post status

| Status | Badge colour | Meaning |
|---|---|---|
| `PENDING` | Grey | Not yet posted |
| `POSTING` | Blue | Upload in progress |
| `POSTED` | Green | Successfully uploaded |
| `FAILED` | Red | Upload failed |
| `SCHEDULED` | Yellow/orange | Deferred for a future publish time |

### Clip Render mode (layout)

| Mode | Badge colour | Meaning |
|---|---|---|
| `SMART_CROP` | Blue | Auto-detects the speaker and keeps them centred in a 9:16 crop |
| `SPATIAL_STACK` | Yellow/orange | Side-by-side: face crop on top, full frame on bottom |
| `CENTER_CROP` | Grey | Simple centre crop, no detection required |

---

## 13. Auto-Created Records Reference

These records are created automatically — you do not need to create them manually.

| Record | When created | Pre-populated from |
|---|---|---|
| `ClipRenderTemplate` | When a `Channel` is first saved | Blank defaults |
| `ClipLayoutConfig` | When a `ClipCandidate` is first saved | `channel.default_render_mode` + `channel.default_layout_config` |
| `ClipStyleConfig` | When a `ClipCandidate` is first saved | Channel's `ClipRenderTemplate` fields |

**To verify `ClipRenderTemplate` exists for a channel:**
Admin → Channels → open channel → scroll to **Clip Render Template** inline.

**To verify `ClipLayoutConfig` and `ClipStyleConfig` exist for a candidate:**
Admin → Clipping → Clip Candidates → open a candidate → scroll to the **Layout Config** and **Style Config** inlines.

If either inline is missing, it means the signal did not fire (e.g. the candidate was created via a migration or fixture rather than a normal save). Fix: open the candidate and save it once — the signal will fire and create the missing records.

---

## 14. Common Failure Scenarios & Fixes

### Job stuck in DOWNLOADING

**Symptom:** Status shows Downloading but no progress after several minutes.

**Diagnosis:** Check Celery worker logs:
```bash
just logs celeryworker
```
Look for `download_clip_source` task errors.

**Common causes:**
- Invalid or private YouTube URL → Update the source URL and retry from INITIALIZING (create a new job)
- Network timeout → Retry is automatic (up to 3 times with exponential backoff)
- yt-dlp needs update → `uv run pip install -U yt-dlp` inside the container

---

### Job stuck in TRANSCRIBING

**Symptom:** Status shows Transcribing but doesn't advance.

**Fix:** From Clipping Jobs list → select job → Action: **"Retry transcription for stuck/failed jobs"** → Go.

---

### Render failed at stage 1 (trim_and_crop)

**Symptom:** ClipRender shows Failed; stage result for `trim_and_crop` shows Failed with an ffmpeg error.

**Common causes:**
- Downloaded file is corrupt or in an unsupported format
- `start_sec` / `end_sec` outside the video's actual duration

**Fix:** Check stage result error message. If file is corrupt, re-download by creating a new Clipping Job. If timestamps are wrong, edit the candidate's `start_sec`/`end_sec`, then:
Admin → Clip Renders → select render → Action: **"Retry full render (from stage 1)"** → Go.

---

### Render failed at captions stage (stage 5)

**Symptom:** Stages 1–4 are Completed; stage 5 (`captions`) shows Failed.

**Common causes:**
- Font not found — the `fontsdir` path doesn't contain the configured caption font
- ASS file could not be written — permissions issue on MEDIA_ROOT

**Fix:** After resolving the underlying issue:
Admin → Clip Renders → select render → Action: **"Retry from captions (stage 4)"** → Go.

---

### All stage results are Skipped

**Symptom:** Render completes quickly with all stages in Skipped status; output video equals the source clip.

**Cause:** All stages have their feature disabled (caption_enabled=False, watermark_enabled=False, etc.) and no media assets are configured.

**Fix:** This is expected behaviour if no enhancements are configured. Enable features in the candidate's Style Config or assign media assets to the channel.

---

### Candidates not created after analysis

**Symptom:** Job advances to `AWAITING_CLIP_APPROVAL` but no candidates appear.

**Cause:** The LLM returned 0 clips (e.g. the source video was too short, or the transcript was empty).

**Check:**
- `transcript_text` on the job — is it populated?
- Celery logs for `analyze_clips` task — did it raise an error?

**Fix:** If the transcript is empty, retry transcription. If the transcript exists but analysis returned nothing, the LLM may need a longer source video or the prompt may need tuning.

---

### ClipStyleConfig or ClipLayoutConfig missing on a candidate

**Symptom:** Opening a candidate shows no Layout Config or Style Config inline.

**Fix:** Open the candidate in the admin and click **Save** without making any changes. The `post_save` signal will fire and auto-create the missing records.

---

*Last updated: 2026-03-29*
*Branch: feature/clip-render-enhancements (merged into main)*
