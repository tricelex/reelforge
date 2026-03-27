# Smart Crop & Spatial Layout for ClipRenderer

**Date:** 2026-03-27
**Status:** Approved — ready for implementation

---

## Problem

The current `ClipRenderer` applies a static center crop (`crop=ih*9/16:ih`) to produce 9:16 output. This fails in two scenarios:

1. **Off-center speakers** — when the speaker occupies the left or right quarter of the frame, they are cropped out entirely.
2. **Multi-region layouts** — streamer content (facecam + gameplay/chat) needs two separate regions from the source frame composited into a single 9:16 output.

Both scenarios must be configurable per `ClipCandidate` in the Django admin, with a channel-level default, before the render runs.

---

## Scope

- Speaker-aware smart cropping with automatic face detection and manual override
- Spatial stack layout: crop two named regions from the same source frame and stack them vertically into 9:16
- Admin inline on `ClipCandidate` with structured fields and a preview image
- Channel-level default render mode (defaults to `SMART_CROP`)
- No changes to the existing `CENTER_CROP` path — zero regression on current renders

---

## Data Model

### `ClipLayoutConfig` (new model)

OneToOne to `ClipCandidate`. Auto-created by a `post_save` signal on `ClipCandidate`, pre-populated from the channel's default.

```python
class ClipLayoutConfig(BaseAbstractModel):

    class RenderMode(models.TextChoices):
        SMART_CROP    = "SMART_CROP",    "Smart Crop (speaker-aware)"
        SPATIAL_STACK = "SPATIAL_STACK", "Spatial Stack (two regions)"
        CENTER_CROP   = "CENTER_CROP",   "Center Crop (static)"

    candidate = models.OneToOneField(
        ClipCandidate,
        on_delete=models.CASCADE,
        related_name="layout_config",
    )
    render_mode = models.CharField(
        max_length=20,
        choices=RenderMode.choices,
        default=RenderMode.SMART_CROP,
    )

    # Smart Crop — manual override (all null = auto-detect)
    manual_crop_x = models.PositiveIntegerField(null=True, blank=True)
    manual_crop_y = models.PositiveIntegerField(null=True, blank=True)
    manual_crop_w = models.PositiveIntegerField(null=True, blank=True)
    manual_crop_h = models.PositiveIntegerField(null=True, blank=True)

    # Spatial Stack — Region A (top slot)
    region_a_label = models.CharField(max_length=100, blank=True, default="Region A")
    region_a_x = models.PositiveIntegerField(null=True, blank=True)
    region_a_y = models.PositiveIntegerField(null=True, blank=True)
    region_a_w = models.PositiveIntegerField(null=True, blank=True)
    region_a_h = models.PositiveIntegerField(null=True, blank=True)

    # Spatial Stack — Region B (bottom slot)
    region_b_label = models.CharField(max_length=100, blank=True, default="Region B")
    region_b_x = models.PositiveIntegerField(null=True, blank=True)
    region_b_y = models.PositiveIntegerField(null=True, blank=True)
    region_b_w = models.PositiveIntegerField(null=True, blank=True)
    region_b_h = models.PositiveIntegerField(null=True, blank=True)
    stack_ratio = models.FloatField(default=0.6)  # top region gets this fraction of output height

    # Detection quality (written back by render task for SMART_CROP)
    face_detected = models.BooleanField(null=True, blank=True)
    detection_confidence = models.FloatField(null=True, blank=True)

    # Preview (written by preview_clip_layout task)
    preview_image = models.ImageField(
        upload_to="clipping/previews/",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Clip Layout Config"
        verbose_name_plural = "Clip Layout Configs"

    def __str__(self) -> str:
        return f"{self.get_render_mode_display()} — {self.candidate}"

    @property
    def has_manual_smart_crop(self) -> bool:
        return all(
            v is not None
            for v in [self.manual_crop_x, self.manual_crop_y, self.manual_crop_w, self.manual_crop_h]
        )

    @property
    def has_spatial_regions(self) -> bool:
        return all(
            v is not None
            for v in [
                self.region_a_x, self.region_a_y, self.region_a_w, self.region_a_h,
                self.region_b_x, self.region_b_y, self.region_b_w, self.region_b_h,
            ]
        )
```

### `RenderMode` constants

To avoid a circular import between `channels/models.py` and `clipping/models.py`, define `RenderMode` choices in a shared location:

New file: `reelforge/clipping/constants.py`

```python
class RenderMode(models.TextChoices):
    SMART_CROP    = "SMART_CROP",    "Smart Crop (speaker-aware)"
    SPATIAL_STACK = "SPATIAL_STACK", "Spatial Stack (two regions)"
    CENTER_CROP   = "CENTER_CROP",   "Center Crop (static)"
```

Both `ClipLayoutConfig` and `Channel` import `RenderMode` from here.

### Channel model additions

Two new fields on `Channel`:

```python
from reelforge.clipping.constants import RenderMode

default_render_mode = models.CharField(
    max_length=20,
    choices=RenderMode.choices,
    default=RenderMode.SMART_CROP,
)
default_layout_config = models.JSONField(
    default=dict,
    blank=True,
    help_text="Default region coordinates for SPATIAL_STACK mode. Keys: region_a_label, region_a_x/y/w/h, region_b_label, region_b_x/y/w/h, stack_ratio.",
)
```

### Auto-creation signal

In `reelforge/clipping/signals.py`, connect to `post_save` on `ClipCandidate`:

```python
@receiver(post_save, sender=ClipCandidate)
def create_layout_config(sender, instance, created, **kwargs):
    if not created:
        return
    channel = instance.clipping_job.channel
    defaults = channel.default_layout_config or {}
    ClipLayoutConfig.objects.get_or_create(
        candidate=instance,
        defaults={
            "render_mode": channel.default_render_mode,
            **defaults,
        },
    )
```

---

## Speaker Detection Service

New file: `reelforge/services/media/speaker_detection.py`

```python
@dataclass
class SpeakerCropResult:
    crop_x: int
    crop_w: int
    crop_h: int
    confidence: float   # fraction of sampled frames with a detected face
    face_detected: bool # False → fell back to center crop

class SpeakerDetectionService:
    def __init__(self, sample_every_n_frames: int = 5) -> None: ...

    def detect(
        self,
        video_path: Path,
        start_sec: float,
        end_sec: float,
    ) -> SpeakerCropResult: ...
```

**Algorithm:**
1. Open video with `cv2.VideoCapture`, seek to `start_sec`
2. Sample every N frames until `end_sec`
3. Run `mediapipe.solutions.face_detection` on each sampled frame
4. Collect face center X positions from all detections
5. If no faces found → `face_detected=False`, `crop_x` defaults to center
6. Use **median** X across all detections for stability (avoids jitter)
7. Clamp crop window: `crop_x = max(0, min(face_center_x - crop_w//2, src_w - crop_w))`
8. `confidence = frames_with_face / total_sampled_frames`

`crop_w` is derived from source dimensions: `crop_w = int(9 / 16 * src_h)`, `crop_h = src_h`.

**New dependencies:** `mediapipe`, `opencv-python-headless`

---

## ClipRenderer Updates

### `ClipRenderConfig` addition

```python
@dataclass
class ClipRenderConfig:
    ...existing fields...
    layout_config: ClipLayoutConfig | None = None
```

### `ClipRenderer._build_ffmpeg_command()` dispatch

```python
def _build_ffmpeg_command(self) -> list[str]:
    lc = self.config.layout_config
    mode = lc.render_mode if lc else "CENTER_CROP"

    if mode == "SMART_CROP":
        vf = self._build_smart_crop_filter(lc)
    elif mode == "SPATIAL_STACK":
        return self._build_spatial_stack_command(lc)
    else:
        vf = self._build_center_crop_filter()

    return [
        "ffmpeg", "-y",
        "-ss", str(self.config.start_sec),
        "-to", str(self.config.end_sec),
        "-i", str(self.config.source_path),
        "-vf", vf,
        "-c:v", "libx264", "-crf", str(self.config.crf), "-preset", self.config.preset,
        "-c:a", "aac", "-b:a", self.config.audio_bitrate,
        "-movflags", "faststart",
        str(self.config.output_path),
    ]
```

**SMART_CROP filter:**
- If `lc.has_manual_smart_crop` → use manual coords directly
- Else → call `SpeakerDetectionService.detect()` and store result in `self.last_speaker_crop_result`
- `ClipRenderer` exposes `last_speaker_crop_result: SpeakerCropResult | None = None` as an instance attribute so the calling task can read detection quality after `render()` returns
- Produces: `crop={crop_w}:{crop_h}:{crop_x}:0,scale={width}:{height},fps={fps}`

**SPATIAL_STACK command** (uses `-filter_complex`):
```
[0:v]crop={a_w}:{a_h}:{a_x}:{a_y},scale={out_w}:{top_h}[top];
[0:v]crop={b_w}:{b_h}:{b_x}:{b_y},scale={out_w}:{bot_h}[bot];
[top][bot]vstack=inputs=2[out]
```
where `top_h = int(output_height * stack_ratio)` and `bot_h = output_height - top_h`.

**CENTER_CROP** (unchanged): `crop=ih*9/16:ih,scale={width}:{height},fps={fps}`

If `layout_config` is `None` → CENTER_CROP (no regression on existing renders).

---

## Preview Task

New Celery task: `preview_clip_layout(candidate_id: str)`

- Queue: `clipping`
- No `time_limit` needed (lightweight)
- Flow:
  1. Load `ClipCandidate` with `select_related("layout_config", "clipping_job")`
  2. Extract one frame at `(start_sec + end_sec) / 2` using `cv2`
  3. If `SMART_CROP` with no manual override: run `SpeakerDetectionService.detect()` to find auto crop window
  4. Draw colored rectangles on the frame using `Pillow`:
     - SMART_CROP: one green rectangle for the crop window
     - SPATIAL_STACK: blue for region A, orange for region B
  5. Save to `clipping/previews/{candidate_id}.jpg`
  6. Write path to `ClipLayoutConfig.preview_image`

---

## `render_clip` Task Updates

```python
candidate = ClipCandidate.objects.select_related(
    "layout_config",
    "clipping_job__channel",
).get(id=clip_candidate_id)

layout_config = getattr(candidate, "layout_config", None)

config = ClipRenderConfig(
    ...existing fields...,
    layout_config=layout_config,
)
renderer = ClipRenderer(config)
renderer.render()

# Write detection quality back to layout_config after render
if layout_config and layout_config.render_mode == ClipLayoutConfig.RenderMode.SMART_CROP:
    result = renderer.last_speaker_crop_result
    if result:
        layout_config.face_detected = result.face_detected
        layout_config.detection_confidence = result.confidence
        layout_config.save(update_fields=["face_detected", "detection_confidence", "updated_at"])
```

---

## Admin

### `ClipLayoutConfigInline` on `ClipCandidateAdmin`

`StackedInline` with fieldsets:

```
[ Render Mode ]   ○ Smart Crop   ○ Spatial Stack   ○ Center Crop

── Smart Crop Override ──────────────────────────────────────────
  Manual Crop X  [    ]   Manual Crop W  [    ]
  Manual Crop Y  [    ]   Manual Crop H  [    ]
  (leave all blank to auto-detect via face detection)
  Face Detected: Yes / No   Confidence: 0.87

── Region A — Top ───────────────────────────────────────────────
  Label  [Facecam        ]
  X  [    ]   Y  [    ]   W  [    ]   H  [    ]

── Region B — Bottom ────────────────────────────────────────────
  Label  [Gameplay       ]
  X  [    ]   Y  [    ]   W  [    ]   H  [    ]
  Stack Ratio (top %)  [ 0.6 ]

── Preview ──────────────────────────────────────────────────────
  [ Generate Preview ]   <preview_image shown here>
```

`face_detected` and `detection_confidence` are read-only display fields.
"Generate Preview" is an admin action on `ClipCandidateAdmin` that calls `preview_clip_layout.delay(candidate.id)`.

### Channel default layout fieldset on `ChannelAdmin`

```
── Default Clip Layout ──────────────────────────────────────────
  Default Render Mode  [ Smart Crop ▼ ]
  Default Layout Config  (JSON, shown only for SPATIAL_STACK)
```

---

## File Changes Summary

| File | Change |
|---|---|
| `reelforge/clipping/constants.py` | New — `RenderMode` TextChoices (shared between clipping + channels) |
| `reelforge/clipping/models.py` | Add `ClipLayoutConfig` model |
| `reelforge/clipping/migrations/` | New migration for `ClipLayoutConfig` |
| `reelforge/clipping/signals.py` | Add `create_layout_config` post_save signal |
| `reelforge/clipping/admin.py` | Add `ClipLayoutConfigInline`, "Generate Preview" action |
| `reelforge/clipping/tasks.py` | Add `preview_clip_layout` task; update `render_clip` |
| `reelforge/channels/models.py` | Add `default_render_mode`, `default_layout_config` |
| `reelforge/channels/migrations/` | New migration for channel fields |
| `reelforge/services/media/speaker_detection.py` | New — `SpeakerDetectionService` |
| `reelforge/services/media/clip_renderer.py` | Update `ClipRenderConfig` + `ClipRenderer` |
| `pyproject.toml` | Add `mediapipe`, `opencv-python-headless` |

---

*Stack: Django 5.2 · Celery · mediapipe · opencv-python-headless · Pillow · FFmpeg*
*Owner: Emmanuel / 29signals*
