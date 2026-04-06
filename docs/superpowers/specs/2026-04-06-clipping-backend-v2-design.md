# Clipping Feature — Backend v2 Design Spec

**Date:** 2026-04-06
**Status:** Approved
**KRD Source:** `reelforge-clipping-krd-final.md` (v2.0, April 2026)
**Scope:** Backend only — Phase 1 (Model Migration + DRF API) and Phase 2 (ML Services Upgrade)
**Frontend (Next.js):** Separate repo, out of scope for this spec.

---

## 1. Overview

This spec covers the complete backend rewrite of the Reelforge Clipping Feature, replacing:
- Channel-scoped models → global / SocialAccount-scoped models
- Django template views + HTMX → DRF ViewSets + REST API
- OpenCV Haar cascade speaker detection → MediaPipe + PyAnnote diarization

The implementation follows **Approach B (domain grouping)**:
1. Models + migrations + constants + signals
2. DRF serializers + ViewSets + SSE + JWT auth + router + delete old views
3. ML services: speaker detection rewrite + analysis helpers + task upgrade

---

## 2. Model Layer Changes

### 2.1 `ClippingJob`

**Remove:**
- `channel` — `ForeignKey(Channel)` (entire field)
- `target_accounts` — `ManyToManyField(SocialAccount)`
- `source_duration_sec` — `PositiveIntegerField` (replace with `FloatField`)

**Add:**
- `social_account` — `ForeignKey("channels.SocialAccount", on_delete=PROTECT, related_name="clipping_jobs")`
- `analysis_manifest` — `JSONField(null=True, blank=True)` (see §2.12 for schema)
- `thumbnail_strip_file` — `FileField(upload_to="clipping/thumbnails/", blank=True, null=True)`
- `waveform_data_file` — `FileField(upload_to="clipping/waveforms/", blank=True, null=True)`
- `source_duration_sec` — `FloatField(null=True, blank=True)` (replaces PositiveIntegerField)

**Update index:** Change `channel` index to `social_account`.

**Note on `SocialAccount` app path:** KRD shows `"accounts.SocialAccount"` but the existing codebase uses `channels.SocialAccount`. Use `"channels.SocialAccount"` — no new app created.

**Keep all FSM transitions as-is.** Add `retry_analysis()` transition: `FAILED → ANALYZING` (new, listed in KRD §7).

---

### 2.2 `ClipRenderTemplate`

**Remove:**
- `channel` — `OneToOneField(Channel)`

**Add:**
- `name` — `CharField(max_length=100, default="Default Template")`
- `is_default` — `BooleanField(default=False)`
- `UniqueConstraint(fields=["is_default"], condition=Q(is_default=True), name="unique_default_render_template")`

**Keep:** All 36 style fields from `ClipRenderStyleMixin`.

**`save()` override:** If `is_default=True`, unset all other templates before saving.

---

### 2.3 `ClipMediaAsset`

**Remove:** `channel` — `ForeignKey(Channel)`

**Add:** `thumbnail` — `ImageField(upload_to="clipping/media_assets/thumbs/", blank=True, null=True)`

**Update index:** Remove `channel` from index, keep `asset_type` + `is_active`.

---

### 2.4 `ClipMusicAsset`

**Remove:** `channel` — `ForeignKey(Channel)`

**Add:** `waveform_file` — `FileField(upload_to="clipping/music_assets/waveforms/", blank=True, null=True)`

**Update index:** Remove `channel` from index.

---

### 2.5 `ClipStyleConfig`

**Add:** `render_template` — `ForeignKey(ClipRenderTemplate, null=True, blank=True, on_delete=SET_NULL)`

---

### 2.6 Models with No Changes

`ClipCandidate`, `ClipLayoutConfig`, `ClipTimedOverlay`, `ClipRender`, `ClipRenderStageResult`, `ClipPost` — keep exactly as existing.

---

### 2.7 Migration Strategy

One migration per logical change (not one giant migration):

1. `0011_clippingjob_remove_channel_add_social_account` — drop `channel` FK + `target_accounts` M2M, add `social_account` FK, add `analysis_manifest` + asset fields, change `source_duration_sec` to FloatField
2. `0012_cliprendertemplate_global` — drop `channel` OneToOne, add `name` + `is_default` + UniqueConstraint
3. `0013_clipmediaasset_global` — drop `channel` FK, add `thumbnail`
4. `0014_clipmusicasset_global` — drop `channel` FK, add `waveform_file`
5. `0015_clipstyleconfig_add_render_template` — add `render_template` FK
6. `0016_seed_default_render_template` — data migration: create `ClipRenderTemplate(name="Default Template", is_default=True)` with defaults from KRD §14

---

### 2.8 Constants (`reelforge/clipping/constants.py`)

Add:
```python
PLATFORM_RENDER_MODE_DEFAULTS: dict[str, str] = {
    "tiktok": RenderMode.SMART_CROP,
    "youtube": RenderMode.CENTER_CROP,
    "instagram": RenderMode.SMART_CROP,
}

PLATFORM_FORMAT_DEFAULTS: dict[str, str] = {
    "tiktok": "VERTICAL_9_16",
    "youtube": "LANDSCAPE_16_9",
    "instagram": "SQUARE_1_1",
}
```

---

### 2.9 Signals (`reelforge/clipping/signals.py`)

**Remove entirely:**
- `create_clip_render_template_for_channel` function
- Its `post_save` connect call in `ClippingConfig.ready()`

**Update `create_layout_config_for_candidate`:**
```python
account = instance.clipping_job.social_account
platform = account.platform
render_mode = PLATFORM_RENDER_MODE_DEFAULTS.get(platform, RenderMode.SMART_CROP)
ClipLayoutConfig.objects.get_or_create(
    candidate=instance,
    defaults={"render_mode": render_mode},
)
```

**Update `create_style_config_for_candidate`:**
```python
template = ClipRenderTemplate.objects.filter(is_default=True).first()
if template is None:
    template = ClipRenderTemplate.objects.first()
style_defaults = template.to_style_defaults() if template is not None else {}
ClipStyleConfig.objects.get_or_create(
    candidate=instance,
    defaults={**style_defaults, "render_template": template},
)
```

**Keep unchanged:** `detect_media_asset_duration`, `detect_music_asset_duration`, `on_clipping_job_transition`.

---

## 3. DRF API Layer

### 3.1 Authentication

**Package:** `djangorestframework-simplejwt`

**Settings:**
```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAdminUser",
    ],
}
```

**URLs:**
- `POST /api/v1/auth/token/` — obtain token pair
- `POST /api/v1/auth/token/refresh/` — refresh access token

**Token settings (reasonable defaults):**
- Access token lifetime: 15 minutes
- Refresh token lifetime: 7 days

---

### 3.2 Serializers (`reelforge/clipping/serializers.py`)

One file for all serializers. Key design decisions:

| Serializer | Notes |
|---|---|
| `ClippingJobListSerializer` | Flat — no nested candidates. Used for list endpoint. |
| `ClippingJobDetailSerializer` | Nested `candidates` (read-only list). |
| `ClipCandidateListSerializer` | Flat — no nested configs. |
| `ClipCandidateDetailSerializer` | Nested `layout_config`, `style_config`, `timed_overlays`. |
| `ClipLayoutConfigSerializer` | All fields writable. |
| `ClipStyleConfigSerializer` | All 36 style fields writable. |
| `ClipTimedOverlaySerializer` | All fields writable. |
| `ClipRenderSerializer` | Nested `stage_results`. |
| `ClipRenderStageResultSerializer` | All fields read-only. |
| `ClipMediaAssetSerializer` | File upload via `multipart/form-data`. |
| `ClipMusicAssetSerializer` | File upload via `multipart/form-data`. |
| `ClipRenderTemplateSerializer` | All 36 style fields writable. |
| `ClipPostSerializer` | Analytics fields read-only. |

All serializers pass `request` via context so file/image fields return absolute URLs.

---

### 3.3 ViewSets

**File structure:**
```
reelforge/clipping/views/
    __init__.py          # Re-exports all ViewSets for router
    jobs.py              # ClippingJobViewSet
    candidates.py        # ClipCandidateViewSet, ClipLayoutConfigViewSet, ClipStyleConfigViewSet
    renders.py           # ClipRenderViewSet
    overlays.py          # ClipTimedOverlayViewSet
    assets.py            # ClipMediaAssetViewSet, ClipMusicAssetViewSet,
                         # ClipRenderTemplateViewSet, ClipPostViewSet
```

#### `ClippingJobViewSet` (ModelViewSet)

Standard CRUD plus custom actions:

| Action | Method | URL | Behaviour |
|---|---|---|---|
| `start_render` | POST | `/jobs/{id}/start-render/` | Verify ≥1 APPROVED candidate, dispatch `render_clip.delay()` per approved candidate, call `job.begin_rendering()`, return `{dispatched_renders, candidate_ids, job_status}` |
| `approve_all` | POST | `/jobs/{id}/approve-all/` | Set all PROPOSED candidates to APPROVED |
| `retry` | POST | `/jobs/{id}/retry/` | Body `{"from_stage": "transcription"\|"analysis"}`, dispatch appropriate task |
| `stream` | GET | `/jobs/{id}/stream/` | Returns `StreamingHttpResponse` from `job_event_stream()` |

List uses `ClippingJobListSerializer`. Retrieve uses `ClippingJobDetailSerializer`.

On `create`: dispatch `download_source_video.delay(job.id)` + `emit_job_event`.

#### `ClipCandidateViewSet` (no create/delete — candidates are created by the analysis task)

Custom actions:

| Action | Method | URL |
|---|---|---|
| `approve` | POST | `/candidates/{id}/approve/` |
| `reject` | POST | `/candidates/{id}/reject/` |
| `undo_reject` | POST | `/candidates/{id}/undo-reject/` |
| `trigger_preview` | POST | `/candidates/{id}/trigger-preview/` |
| `preview_status` | GET | `/candidates/{id}/preview-status/` |

Filterable by `?job={id}&status=PROPOSED`.

#### `ClipLayoutConfigViewSet` (retrieve + partial_update only — no create/delete)

Custom action: `reset_crop` (POST) — clears all `manual_crop_*` fields.

#### `ClipStyleConfigViewSet` (retrieve + partial_update only)

Custom action: `apply_template` (POST) — body `{"template_id": "uuid"}`, copies all style fields from template to config.

#### `ClipRenderViewSet` (list + retrieve — no create/update/delete from API)

Custom actions:
- `resume` (POST) — dispatches `render_clip.delay(start_from_stage=render.paused_at_stage + 1, clip_render_id=render.id)`
- `rerun` (POST) — URL: `/renders/{id}/rerun/{stage_order}/`
- `download` (GET) — returns signed URL for `video_file`

#### `ClipTimedOverlayViewSet` — full CRUD. Filterable by `?candidate={id}`.

#### `ClipMediaAssetViewSet` — full CRUD. Filterable by `?asset_type=INTRO`.

#### `ClipMusicAssetViewSet` — full CRUD.

#### `ClipRenderTemplateViewSet` — full CRUD.
Custom action: `set_default` (POST) — sets `is_default=True` on this template.
Delete blocked if `is_default=True`.

#### `ClipPostViewSet` — list + retrieve only.
Custom action: `sync_analytics` (POST) — dispatches `sync_clip_analytics.delay(post.id)`.

---

### 3.4 SSE (`reelforge/clipping/sse.py`)

```python
def emit_job_event(job_id: str, event_type: str, data: dict) -> None:
    """Publish event to Redis pub/sub channel for a job. Called from Celery tasks."""

def job_event_stream(job_id: str) -> Generator[str, None, None]:
    """Generator yielding SSE-formatted strings. Subscribes to Redis channel."""
```

Events sent with `emit_job_event` at every status transition in every task:

| Event | Emitted by |
|---|---|
| `status_changed` | All tasks on FSM transition |
| `analysis_complete` | `analyze_clips` |
| `render_update` | `render_clip` per stage |
| `render_stage_complete` | `render_clip` per stage |
| `render_paused` | `render_clip` on gate |
| `render_complete` | `render_clip` on success |
| `render_failed` | `render_clip` on exception |
| `post_complete` | `post_clip` on success |
| `job_failed` | Any task `mark_failed()` |
| `preview_ready` | `preview_clip_layout` |

---

### 3.5 Router Registration (`config/urls.py`)

```python
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

urlpatterns += [
    path("api/v1/", include(router.urls)),
    path("api/v1/auth/", include("rest_framework_simplejwt.urls")),
]
```

---

### 3.6 Files Deleted

- `reelforge/clipping/views/jobs.py` (old template view)
- `reelforge/clipping/views/candidates.py` (old template view)
- `reelforge/clipping/views/renders.py` (old template view)
- `reelforge/clipping/urls.py` (old URL conf)
- `reelforge/templates/clipping/` (all templates)
- `reelforge/clipping/tests/test_views_phase_b.py` (replaced by `tests/test_api.py`)

---

### 3.7 Tests (`reelforge/clipping/tests/test_api.py`)

New test module covering:
- JWT obtain + use
- Job CRUD + `start_render` + `approve_all` actions
- Candidate approve/reject/undo
- Layout config PATCH + `reset_crop`
- Style config PATCH + `apply_template`
- Render `resume` + `rerun`
- Asset upload
- Template `set_default`

Existing tests (`test_models.py`, `test_tasks.py`, `test_signals.py`, `test_services.py`) updated to remove channel references and update fixtures.

---

## 4. ML Services Layer (Phase 2)

### 4.1 New Dependencies (Phase 2 additions)

Phase 1 adds: `djangorestframework>=3.14`, `djangorestframework-simplejwt>=5.3`

Phase 2 adds:
```toml
# pyproject.toml
mediapipe = ">=0.10"
"pyannote.audio" = ">=3.1"
"scenedetect[opencv]" = ">=0.6"
```

Remove: `opencv-python` (MediaPipe ships its own OpenCV bindings).

New env var: `HUGGINGFACE_TOKEN` — required for PyAnnote model download.

---

### 4.2 Speaker Detection Service (`reelforge/services/media/speaker_detection.py`)

Full rewrite. Exposes:

```python
@dataclass
class SpeakerCropResult:
    crop_x: int
    crop_w: int
    crop_h: int
    confidence: float
    face_detected: bool
    speaker_id: str | None = None

@dataclass
class DiarizationSegment:
    speaker_id: str
    start: float
    end: float

class SpeakerDetectionService:
    def diarize(self, video_path: str) -> list[DiarizationSegment]: ...
    def detect_faces_for_segment(self, video_path, start_sec, end_sec, sample_every_n_frames=5) -> list[dict]: ...
    def detect(self, video_path, start_sec, end_sec, manual_crop_x=None, ...) -> SpeakerCropResult: ...
```

`detect()` is the primary method called from `TrimAndCropStage`. Implements:
1. Manual crop override takes full precedence
2. MediaPipe face detection across sampled frames
3. Median face-centre X to reduce jitter
4. Fallback to centre crop if no faces found

Lazy-loaded `_face_detector` and `_diarizer` (avoid loading models at import time).

---

### 4.3 Analysis Helpers (`reelforge/clipping/analysis_helpers.py`)

New file:

```python
def run_speaker_diarization(video_path: str) -> dict: ...
def run_scene_detection(video_path: str) -> list[float]: ...
def run_face_detection_for_speakers(video_path: str, diarization: dict) -> dict: ...
def merge_transcript_with_diarization(transcript_json: dict, diarization: dict) -> list[dict]: ...
def build_analysis_manifest(
    transcript: list[dict],
    diarization: dict,
    face_mappings: dict,
    scene_cuts: list[float],
    candidates: list,
) -> dict: ...
```

`build_analysis_manifest` produces the §6.12 schema: `schema_version`, `transcript` (word-level with speaker_id), `speakers` (segments + face_samples), `scene_cuts`, `ai_clip_suggestions`, `waveform_url`, `thumbnail_strip_url`, `completed_at`.

---

### 4.4 `ClipAnalysisService` Updates (`reelforge/clipping/services.py`)

**Update `analyze()` signature:**
```python
def analyze(
    self,
    enriched_transcript: list[dict] | None = None,
    diarization: dict | None = None,
) -> list[ClipCandidate]: ...
```

**Remove:** Reference to `job.channel.niche_category`.

**Add to system prompt context:**
```python
platform = self.job.social_account.platform
account_name = self.job.social_account.username
```

**Update LLM call:**
```python
llm = get_llm_provider(self.job.social_account)  # was channel
```

---

### 4.5 `analyze_clips` Task Rewrite

**Remove:** Entire auto-approve block.

**New flow:**
```
1. run_speaker_diarization(job.downloaded_file.path)
2. run_scene_detection(job.downloaded_file.path)
3. run_face_detection_for_speakers(...)
4. merge_transcript_with_diarization(job.transcript_json, diarization_result)
5. ClipAnalysisService.analyze(enriched_transcript=..., diarization=...)
6. build_analysis_manifest(...)
7. job.analysis_manifest = manifest
8. job.await_clip_approval()
9. job.save(update_fields=[...])
10. emit_job_event("analysis_complete", {...})
```

---

### 4.6 `PipelineRenderConfig` Update

**Remove:** `channel` field.

**Add:** `social_account_platform: str = "tiktok"`

Update `render_clip` task to pass `social_account_platform=candidate.clipping_job.social_account.platform`.

---

### 4.7 `TrimAndCropStage` Update

Update call site to `SpeakerDetectionService().detect()` — same method name, same return type (`SpeakerCropResult`). Existing write-back logic (face_detected, detection_confidence) unchanged.

---

## 5. What Is Not Changing

- `ClipRenderPipeline` core logic (stages 1–10)
- `ClipRender`, `ClipRenderStageResult` models
- `ClipCandidate`, `ClipLayoutConfig`, `ClipTimedOverlay`, `ClipPost` models
- `download_source_video`, `transcribe_video`, `render_clip`, `preview_clip_layout`, `preview_clip_style`, `post_clip`, `sync_clip_analytics` tasks (except SSE emit calls added)
- Gate mechanism (`GatePausedException`, `pause_after_stages`) — unchanged
- Admin (Unfold) — existing admin classes updated to remove channel references, no structural changes

---

## 6. Error Handling Notes

- If `SpeakerDetectionService.diarize()` fails, `analyze_clips` catches the exception, logs it, and falls back to `enriched_transcript=None` (GPT analysis runs without diarization context rather than failing the entire job)
- If `run_scene_detection()` fails, log + continue with `scene_cuts=[]`
- `ClipRenderTemplate` delete blocked at the ViewSet level (not DB constraint) if `is_default=True`

---

## 7. Open Items / Assumptions

- `get_llm_provider()` in `services/providers/registry.py` currently accepts a `Channel`. It will need to accept `SocialAccount` — or a refactor to accept no argument (single global LLM config). **Assumption:** Update call signature to `get_llm_provider(account: SocialAccount)`, assuming the registry can resolve LLM config from account or from settings directly.
- `HUGGINGFACE_TOKEN` needs to be added to `.envs/.local/.django` and `.envs/.production/.django`. Not committed.
- PyAnnote requires a one-time model download on first run — Docker image build should pre-download or the first task run will be slow.
