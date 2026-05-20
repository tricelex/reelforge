# Manual Clip Bypass — Design Spec

**Date:** 2026-05-20
**Status:** Approved

---

## Problem

When an operator uploads a video they have already edited (a highlight reel, a finished short, etc.), running the full transcription → AI analysis → clip-candidate pipeline is wasteful and undesirable. The operator wants to skip the AI analysis step and go directly to the candidate configure stage, where they can trim, style, and render the video as a single clip.

---

## Solution Overview

Add a `skip_analysis` flag to `ClippingJob`. When set, the pipeline still runs transcription (needed for caption rendering) but bypasses the analysis step. After transcription it creates a single `ClipCandidate` with `is_manual=True` spanning the full video, transitions the job to `AWAITING_CLIP_APPROVAL`, and hands control to the operator.

A companion API action and admin action provide an "emergency override" path for jobs already in-flight or in a failed state.

---

## Architecture

### Flow — normal path (unchanged)

```
INITIALIZING → DOWNLOADING → TRANSCRIBING → ANALYZING → AWAITING_CLIP_APPROVAL
```

### Flow — bypass path (`skip_analysis=True`)

```
INITIALIZING → DOWNLOADING → TRANSCRIBING → AWAITING_CLIP_APPROVAL
                                              (single is_manual candidate created here)
```

---

## Model Changes

### `ClippingJob`

Add one field:

```python
skip_analysis = models.BooleanField(default=False)
```

Add one FSM transition:

```python
@transition(
    field=status,
    source=[Status.TRANSCRIBING, Status.ANALYZING, Status.FAILED],
    target=Status.AWAITING_CLIP_APPROVAL,
)
def skip_to_candidates(self) -> None:
    pass
```

The broad `source` list covers three cases:
- Automatic post-transcription bypass (source = `TRANSCRIBING`)
- Admin/API override on a job stuck in analysis (source = `ANALYZING`)
- Recovery of a failed job the operator wants to salvage manually (source = `FAILED`)

### `ClipCandidate`

Add one field:

```python
is_manual = models.BooleanField(default=False)
```

Modify `clean()`: when `is_manual=True`, skip the 30s minimum, 180s maximum, and overlap validation checks. Manual candidates represent operator-defined segments; the AI-clip constraints do not apply.

### Migration

One migration covering both new fields: `add_skip_analysis_and_is_manual`.

---

## Task Change (`tasks.py`)

In `transcribe_video`, replace the unconditional `analyze_clips.delay(...)` call with a branch:

```python
if job.skip_analysis:
    job.skip_to_candidates()
    job.save(update_fields=["status", "updated_at"])
    # For UPLOAD jobs, source_duration_sec is not set during download —
    # probe the file here so the manual candidate has a valid end_sec.
    duration = job.source_duration_sec
    if duration is None and job.downloaded_file:
        import ffmpeg
        probe = ffmpeg.probe(str(Path(settings.MEDIA_ROOT) / job.downloaded_file.name))
        duration = float(probe["format"]["duration"])
        job.source_duration_sec = duration
        job.save(update_fields=["source_duration_sec", "updated_at"])
    ClipCandidate.objects.create(
        clipping_job=job,
        title=job.source_title or "Full Video",
        start_sec=0.0,
        end_sec=duration or 0.0,
        is_manual=True,
    )
    emit_job_event(str(job.id), "status_changed", {"status": job.status})
else:
    analyze_clips.delay(clipping_job_id)
```

The existing `post_save` signals on `ClipCandidate` auto-create `ClipLayoutConfig` and `ClipStyleConfig` for the new manual candidate — no signal changes required.

---

## Admin Action (`admin.py`)

Add a `ClippingJobAdmin` action `"fast_forward_to_candidates"` (display name: "Fast-forward to candidates"):

1. For each selected job, check `can_proceed(job.skip_to_candidates)`.
2. If yes: call `job.skip_to_candidates()`, save, create the manual candidate (same logic as task branch), emit SSE event.
3. If no: add a `messages.warning` and skip that job.

This surfaces on jobs in `TRANSCRIBING`, `ANALYZING`, or `FAILED` states. The action does not require `skip_analysis=True` on the job — it is always available when the FSM state allows it.

---

## API Changes

### Serializers

**`ClippingJobListSerializer`** — add `skip_analysis` to `fields`. It must be writable (not in `read_only_fields`) so it can be set at job creation time. All downstream serializers that inherit from it (`ClippingJobDetailSerializer`) pick it up automatically.

**`ClipCandidateListSerializer`** — add `is_manual` to `fields` and `read_only_fields`. The frontend needs it to unlock time-range editing on manual candidates.

**`ClipCandidateDetailSerializer`** — add `is_manual` to `fields` and `read_only_fields`.

### New API Action

```
POST /api/v1/clipping/jobs/{id}/skip-to-candidates/
```

Emergency override for in-flight jobs. No request body required.

- Returns `400` if `can_proceed(job.skip_to_candidates)` is `False`, with a descriptive message.
- On success: performs transition + manual candidate creation + SSE emit, returns the full `ClippingJobDetailSerializer` response with HTTP 200.
- Idempotency note: if the job already has candidates and `AWAITING_CLIP_APPROVAL` is unreachable from the current state, the 400 prevents duplicate candidates.

---

## Frontend Changes (Next.js)

The frontend spec lives at `docs/superpowers/specs/2026-05-09-clipping-frontend-design.md`. Three touch points:

### 1. Job creation form

Add a "Skip AI analysis" toggle (boolean). Maps to `skip_analysis: true` in the `POST /api/v1/clipping/jobs/` body. Show helper text: "Upload a pre-edited video and go directly to the clip configure stage."

### 2. Job list / job detail

- Show a "Manual" badge on jobs where `skip_analysis=true`.
- On jobs with status `TRANSCRIBING`, `ANALYZING`, or `FAILED`: show a "Skip to candidates" button. On click, call `POST /api/v1/clipping/jobs/{id}/skip-to-candidates/`. On success, invalidate/refetch the job. On 400, surface the error message.

### 3. Candidate card / configure page

When `is_manual=true`:
- Unlock `start_sec` and `end_sec` for inline editing. Both fields are already writable via `PATCH /api/v1/clipping/candidates/{id}/` — only the UI guard needs removing.
- Show a "Manual clip" badge on the candidate card.
- `title` editing is already available; no change needed.

---

## What Does NOT Change

- `download_source_video` task — unmodified. Download runs regardless of `skip_analysis`.
- `transcribe_video` task — only the final dispatch branch changes; all transcription logic is untouched.
- `ClipLayoutConfig` and `ClipStyleConfig` creation — handled by existing `post_save` signals; no changes.
- `render_clip` task — unmodified. Manual candidates render identically to AI candidates.
- `ClipCandidate.clean()` overlap check — only skipped when `is_manual=True`; AI candidates are unchanged.
- All other FSM transitions — untouched.

---

## Testing Notes

- Unit test `ClipCandidate.clean()` with `is_manual=True` and duration > 180s — should pass.
- Unit test `ClipCandidate.clean()` with `is_manual=False` and duration > 180s — should raise `ValidationError`.
- Task test: mock `job.skip_analysis=True` → assert `analyze_clips` is NOT dispatched and one `ClipCandidate` is created with `is_manual=True`.
- Task test: mock `job.skip_analysis=False` → assert `analyze_clips` IS dispatched and no manual candidate is created.
- API test: `POST skip-to-candidates` on a `TRANSCRIBING` job → 200, job transitions, candidate created.
- API test: `POST skip-to-candidates` on a `COMPLETED` job → 400.
