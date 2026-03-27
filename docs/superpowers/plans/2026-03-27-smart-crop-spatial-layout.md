# Smart Crop & Spatial Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static center-crop in `ClipRenderer` with speaker-aware smart crop and spatial stack layout modes, configurable per `ClipCandidate` in admin with a channel-level default.

**Architecture:** A new `ClipLayoutConfig` model (OneToOne to `ClipCandidate`) stores the render mode and region coordinates. `ClipRenderer` dispatches to different FFmpeg filter strategies based on mode. A `SpeakerDetectionService` uses mediapipe face detection to find stable crop coordinates when no manual override is set.

**Tech Stack:** Django 5.2, mediapipe, opencv-python-headless, Pillow (already installed), ffmpeg-python, Celery, Unfold admin

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `***REMOVED***/clipping/constants.py` | Create | `RenderMode` TextChoices (shared by clipping + channels) |
| `***REMOVED***/clipping/models.py` | Modify | Add `ClipLayoutConfig` model |
| `***REMOVED***/clipping/migrations/0002_cliplayout_config.py` | Create | Migration for `ClipLayoutConfig` |
| `***REMOVED***/channels/models.py` | Modify | Add `default_render_mode`, `default_layout_config` to `Channel` |
| `***REMOVED***/channels/migrations/0011_channel_default_render_mode.py` | Create | Migration for channel fields |
| `***REMOVED***/clipping/signals.py` | Modify | Auto-create `ClipLayoutConfig` on `ClipCandidate` save |
| `***REMOVED***/clipping/tests/factories.py` | Modify | Add `ClipLayoutConfigFactory` |
| `***REMOVED***/services/media/speaker_detection.py` | Create | `SpeakerDetectionService` + `SpeakerCropResult` |
| `***REMOVED***/services/media/clip_renderer.py` | Modify | Add `layout_config` field; dispatch to new render modes |
| `***REMOVED***/clipping/tasks.py` | Modify | Add `preview_clip_layout` task; update `render_clip` |
| `***REMOVED***/clipping/admin.py` | Modify | Add `ClipLayoutConfigInline`; generate preview action |
| `***REMOVED***/channels/admin.py` | Modify | Add "Default Clip Layout" fieldset to `ChannelAdmin` |
| `***REMOVED***/clipping/tests/test_models.py` | Modify | Tests for `ClipLayoutConfig` properties |
| `***REMOVED***/clipping/tests/test_renderer.py` | Modify | Tests for new render modes |
| `***REMOVED***/clipping/tests/test_speaker_detection.py` | Create | Unit tests for `SpeakerDetectionService` |
| `pyproject.toml` | Modify | Add `mediapipe`, `opencv-python-headless` |

---

## Task 1: Add Dependencies and RenderMode Constants

**Files:**
- Modify: `pyproject.toml`
- Create: `***REMOVED***/clipping/constants.py`

- [ ] **Step 1: Add dependencies to pyproject.toml**

In `pyproject.toml`, add to the `dependencies` list (after `pillow==12.1.1`):

```toml
"mediapipe>=0.10.0",
"opencv-python-headless>=4.9.0",
```

- [ ] **Step 2: Install new dependencies**

```bash
uv sync
```

Expected: resolves and installs mediapipe and opencv-python-headless without errors.

- [ ] **Step 3: Create constants.py**

Create `***REMOVED***/clipping/constants.py`:

```python
from __future__ import annotations

from django.db import models


class RenderMode(models.TextChoices):
    SMART_CROP = "SMART_CROP", "Smart Crop (speaker-aware)"
    SPATIAL_STACK = "SPATIAL_STACK", "Spatial Stack (two regions)"
    CENTER_CROP = "CENTER_CROP", "Center Crop (static)"
```

- [ ] **Step 4: Verify imports work**

```bash
uv run python -c "from ***REMOVED***.clipping.constants import RenderMode; print(RenderMode.choices)"
```

Expected: `[('SMART_CROP', 'Smart Crop (speaker-aware)'), ('SPATIAL_STACK', 'Spatial Stack (two regions)'), ('CENTER_CROP', 'Center Crop (static)')]`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock ***REMOVED***/clipping/constants.py
git commit -m "feat(clipping): add RenderMode constants and mediapipe/opencv dependencies"
```

---

## Task 2: ClipLayoutConfig Model

**Files:**
- Modify: `***REMOVED***/clipping/models.py`
- Create: migration (auto-generated)
- Modify: `***REMOVED***/clipping/tests/test_models.py`

- [ ] **Step 1: Write failing tests for ClipLayoutConfig**

Add to `***REMOVED***/clipping/tests/test_models.py`:

```python
from ***REMOVED***.clipping.models import ClipLayoutConfig


@pytest.mark.django_db
def test_clip_layout_config_default_render_mode() -> None:
    candidate = ClipCandidateFactory()
    config = ClipLayoutConfig.objects.create(candidate=candidate)
    assert config.render_mode == "SMART_CROP"


@pytest.mark.django_db
def test_has_manual_smart_crop_true_when_all_fields_set() -> None:
    candidate = ClipCandidateFactory()
    config = ClipLayoutConfig(
        candidate=candidate,
        manual_crop_x=100,
        manual_crop_y=0,
        manual_crop_w=405,
        manual_crop_h=720,
    )
    assert config.has_manual_smart_crop is True


@pytest.mark.django_db
def test_has_manual_smart_crop_false_when_any_field_null() -> None:
    candidate = ClipCandidateFactory()
    config = ClipLayoutConfig(
        candidate=candidate,
        manual_crop_x=100,
        manual_crop_y=0,
        manual_crop_w=None,
        manual_crop_h=720,
    )
    assert config.has_manual_smart_crop is False


@pytest.mark.django_db
def test_has_spatial_regions_true_when_all_ab_fields_set() -> None:
    candidate = ClipCandidateFactory()
    config = ClipLayoutConfig(
        candidate=candidate,
        region_a_x=0, region_a_y=0, region_a_w=400, region_a_h=300,
        region_b_x=880, region_b_y=420, region_b_w=400, region_b_h=300,
    )
    assert config.has_spatial_regions is True


@pytest.mark.django_db
def test_has_spatial_regions_false_when_region_b_missing() -> None:
    candidate = ClipCandidateFactory()
    config = ClipLayoutConfig(
        candidate=candidate,
        region_a_x=0, region_a_y=0, region_a_w=400, region_a_h=300,
    )
    assert config.has_spatial_regions is False


@pytest.mark.django_db
def test_clip_layout_config_str() -> None:
    candidate = ClipCandidateFactory()
    config = ClipLayoutConfig.objects.create(candidate=candidate)
    assert "Smart Crop" in str(config)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_models.py -k "layout_config" -v
```

Expected: ImportError or `ClipLayoutConfig` not found.

- [ ] **Step 3: Add ClipLayoutConfig to clipping/models.py**

At the bottom of `***REMOVED***/clipping/models.py`, add these imports at the top of the file (after existing imports):

```python
from ***REMOVED***.clipping.constants import RenderMode as ClipRenderMode
```

Then add `ClipLayoutConfig` after `ClipPost`:

```python
class ClipLayoutConfig(BaseAbstractModel):
    """Stores render mode and layout parameters for a ClipCandidate."""

    # Expose RenderMode for external access (e.g. tasks, admin)
    RenderMode = ClipRenderMode

    candidate = models.OneToOneField(
        ClipCandidate,
        on_delete=models.CASCADE,
        related_name="layout_config",
    )
    render_mode = models.CharField(
        max_length=20,
        choices=ClipRenderMode.choices,
        default=ClipRenderMode.SMART_CROP,
    )

    # Smart Crop manual override — all null means auto-detect
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
    # Fraction of output height given to region A (top). Region B gets 1 - stack_ratio.
    stack_ratio = models.FloatField(default=0.6)

    # Detection quality — written back by render_clip task after SMART_CROP render
    face_detected = models.BooleanField(null=True, blank=True)
    detection_confidence = models.FloatField(null=True, blank=True)

    # Preview image — written by preview_clip_layout task
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
        """True only when all four manual crop fields are set."""
        return all(
            v is not None
            for v in [
                self.manual_crop_x,
                self.manual_crop_y,
                self.manual_crop_w,
                self.manual_crop_h,
            ]
        )

    @property
    def has_spatial_regions(self) -> bool:
        """True only when all eight region A + B coordinate fields are set."""
        return all(
            v is not None
            for v in [
                self.region_a_x, self.region_a_y, self.region_a_w, self.region_a_h,
                self.region_b_x, self.region_b_y, self.region_b_w, self.region_b_h,
            ]
        )
```

- [ ] **Step 4: Generate and run migration**

```bash
uv run python manage.py makemigrations clipping --name cliplayout_config
uv run python manage.py migrate
```

Expected: migration created at `***REMOVED***/clipping/migrations/0002_cliplayout_config.py`, applies cleanly.

- [ ] **Step 5: Run tests**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_models.py -k "layout_config" -v --create-db
```

Expected: all 6 new tests pass.

- [ ] **Step 6: Commit**

```bash
git add ***REMOVED***/clipping/models.py ***REMOVED***/clipping/migrations/ ***REMOVED***/clipping/tests/test_models.py
git commit -m "feat(clipping): add ClipLayoutConfig model with render mode and region fields"
```

---

## Task 3: Channel Default Layout Fields

**Files:**
- Modify: `***REMOVED***/channels/models.py`
- Create: migration (auto-generated)

- [ ] **Step 1: Add fields to Channel model**

In `***REMOVED***/channels/models.py`, add this import at the top (after existing imports):

```python
from ***REMOVED***.clipping.constants import RenderMode as ClipRenderMode
```

Then find `class Channel(BaseAbstractModel):` and add these two fields after `channel_outro_file`:

```python
    # Default layout for clips generated from this channel
    default_render_mode = models.CharField(
        max_length=20,
        choices=ClipRenderMode.choices,
        default=ClipRenderMode.SMART_CROP,
        help_text="Default render mode applied to new ClipCandidates from this channel.",
    )
    default_layout_config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Default region coordinates for SPATIAL_STACK mode. "
            "Keys: region_a_label, region_a_x, region_a_y, region_a_w, region_a_h, "
            "region_b_label, region_b_x, region_b_y, region_b_w, region_b_h, stack_ratio."
        ),
    )
```

- [ ] **Step 2: Generate and run migration**

```bash
uv run python manage.py makemigrations channels --name channel_default_render_mode
uv run python manage.py migrate
```

Expected: migration at `***REMOVED***/channels/migrations/0011_channel_default_render_mode.py`, applies cleanly.

- [ ] **Step 3: Write and run test**

Add to `***REMOVED***/channels/tests/test_models.py` (create the file if it doesn't exist):

```python
from __future__ import annotations

import pytest

from ***REMOVED***.channels.tests.factories import ChannelFactory


@pytest.mark.django_db
def test_channel_default_render_mode_is_smart_crop() -> None:
    channel = ChannelFactory()
    assert channel.default_render_mode == "SMART_CROP"


@pytest.mark.django_db
def test_channel_default_layout_config_is_empty_dict() -> None:
    channel = ChannelFactory()
    assert channel.default_layout_config == {}
```

```bash
uv run pytest ***REMOVED***/channels/tests/test_models.py -v --create-db
```

Expected: both tests pass.

- [ ] **Step 4: Commit**

```bash
git add ***REMOVED***/channels/models.py ***REMOVED***/channels/migrations/ ***REMOVED***/channels/tests/
git commit -m "feat(channels): add default_render_mode and default_layout_config fields"
```

---

## Task 4: Auto-Creation Signal

When a `ClipCandidate` is saved for the first time, a `ClipLayoutConfig` is automatically created using the channel's defaults.

**Files:**
- Modify: `***REMOVED***/clipping/signals.py`
- Modify: `***REMOVED***/clipping/tests/factories.py`
- Create/Modify: `***REMOVED***/clipping/tests/test_signals.py`

- [ ] **Step 1: Write failing test**

Create `***REMOVED***/clipping/tests/test_signals.py`:

```python
from __future__ import annotations

import pytest

from ***REMOVED***.clipping.models import ClipLayoutConfig
from ***REMOVED***.clipping.tests.factories import ClipCandidateFactory
from ***REMOVED***.channels.tests.factories import ChannelFactory
from ***REMOVED***.clipping.tests.factories import ClippingJobFactory


@pytest.mark.django_db
def test_layout_config_auto_created_on_candidate_save() -> None:
    candidate = ClipCandidateFactory()
    assert ClipLayoutConfig.objects.filter(candidate=candidate).exists()


@pytest.mark.django_db
def test_layout_config_inherits_channel_default_render_mode() -> None:
    channel = ChannelFactory(default_render_mode="CENTER_CROP")
    job = ClippingJobFactory(channel=channel)
    candidate = ClipCandidateFactory(clipping_job=job)
    config = ClipLayoutConfig.objects.get(candidate=candidate)
    assert config.render_mode == "CENTER_CROP"


@pytest.mark.django_db
def test_layout_config_not_duplicated_on_second_save() -> None:
    candidate = ClipCandidateFactory()
    candidate.title = "Updated title"
    candidate.save()
    assert ClipLayoutConfig.objects.filter(candidate=candidate).count() == 1
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_signals.py -v
```

Expected: all three tests fail (no auto-creation logic yet).

- [ ] **Step 3: Update signals.py**

Replace the contents of `***REMOVED***/clipping/signals.py` with:

```python
from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from django_fsm.signals import post_transition

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipLayoutConfig
from ***REMOVED***.clipping.models import ClippingJob

logger = logging.getLogger("***REMOVED***.clipping")


def on_clipping_job_transition(sender, instance, name, source, target, **kwargs):
    """Log ClippingJob FSM failures."""
    if target == ClippingJob.Status.FAILED:
        logger.error(
            "ClippingJob failed",
            extra={"clipping_job_id": str(instance.id), "last_error": instance.last_error},
        )


post_transition.connect(on_clipping_job_transition, sender=ClippingJob)


@receiver(post_save, sender=ClipCandidate)
def create_layout_config_for_candidate(
    sender,
    instance: ClipCandidate,
    created: bool,
    **kwargs,
) -> None:
    """Auto-create a ClipLayoutConfig when a ClipCandidate is first saved.

    Pre-populates from channel.default_render_mode and channel.default_layout_config
    so new candidates inherit the channel's preferred layout without manual setup.
    """
    if not created:
        return
    channel = instance.clipping_job.channel
    channel_defaults: dict = channel.default_layout_config or {}
    ClipLayoutConfig.objects.get_or_create(
        candidate=instance,
        defaults={
            "render_mode": channel.default_render_mode,
            **channel_defaults,
        },
    )
```

- [ ] **Step 4: Add ClipLayoutConfigFactory to factories.py**

In `***REMOVED***/clipping/tests/factories.py`, add this import at the top:

```python
from ***REMOVED***.clipping.models import ClipLayoutConfig
```

And add the factory at the bottom:

```python
class ClipLayoutConfigFactory(DjangoModelFactory[ClipLayoutConfig]):
    candidate = factory.SubFactory(ClipCandidateFactory)
    render_mode = ClipLayoutConfig.RenderMode.SMART_CROP

    class Meta:
        model = ClipLayoutConfig
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_signals.py -v
```

Expected: all three tests pass.

- [ ] **Step 6: Run full clipping test suite to check for regressions**

```bash
uv run pytest ***REMOVED***/clipping/tests/ -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add ***REMOVED***/clipping/signals.py ***REMOVED***/clipping/tests/factories.py ***REMOVED***/clipping/tests/test_signals.py
git commit -m "feat(clipping): auto-create ClipLayoutConfig from channel defaults on candidate save"
```

---

## Task 5: SpeakerDetectionService

**Files:**
- Create: `***REMOVED***/services/media/speaker_detection.py`
- Create: `***REMOVED***/clipping/tests/test_speaker_detection.py`

- [ ] **Step 1: Write failing tests**

Create `***REMOVED***/clipping/tests/test_speaker_detection.py`:

```python
from __future__ import annotations

import statistics
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from ***REMOVED***.services.media.speaker_detection import SpeakerCropResult
from ***REMOVED***.services.media.speaker_detection import SpeakerDetectionService


def _make_mock_cap(width: int = 1280, height: int = 720, fps: float = 30.0, frame_count: int = 150):
    """Return a mock cv2.VideoCapture that yields black frames."""
    import numpy as np

    cap = MagicMock()
    cap.get.side_effect = lambda prop: {
        3: width,   # CAP_PROP_FRAME_WIDTH
        4: height,  # CAP_PROP_FRAME_HEIGHT
        5: fps,     # CAP_PROP_FPS
    }.get(prop, 0)
    cap.isOpened.return_value = True

    black_frame = np.zeros((height, width, 3), dtype="uint8")
    # Simulate read() returning True for frame_count frames then False
    reads = [(True, black_frame)] * frame_count + [(False, None)]
    cap.read.side_effect = reads
    return cap


def _make_face_detection_result(face_center_x_rel: float, bbox_width_rel: float = 0.1):
    """Return a mock mediapipe face detection result with a face at a given relative X."""
    detection = MagicMock()
    bbox = MagicMock()
    bbox.xmin = face_center_x_rel - bbox_width_rel / 2
    bbox.width = bbox_width_rel
    bbox.ymin = 0.2
    bbox.height = 0.3
    detection.location_data.relative_bounding_box = bbox
    result = MagicMock()
    result.detections = [detection]
    return result


def test_speaker_detection_returns_speaker_crop_result_dataclass() -> None:
    service = SpeakerDetectionService()
    with (
        patch("cv2.VideoCapture", return_value=_make_mock_cap()),
        patch("mediapipe.solutions.face_detection.FaceDetection") as mock_fd,
    ):
        mock_fd.return_value.__enter__.return_value.process.return_value = (
            _make_face_detection_result(0.3)  # face at 30% of width = x=384 on 1280w
        )
        result = service.detect(Path("/tmp/fake.mp4"), 0.0, 5.0)

    assert isinstance(result, SpeakerCropResult)
    assert result.face_detected is True
    assert result.confidence > 0.0


def test_speaker_detection_centers_on_face() -> None:
    """Face at 25% of 1280px wide frame → crop_x should be shifted left of center."""
    service = SpeakerDetectionService(sample_every_n_frames=1)
    with (
        patch("cv2.VideoCapture", return_value=_make_mock_cap(width=1280, height=720)),
        patch("mediapipe.solutions.face_detection.FaceDetection") as mock_fd,
    ):
        # Face center at x=0.25 relative → absolute = 320px
        mock_fd.return_value.__enter__.return_value.process.return_value = (
            _make_face_detection_result(0.25)
        )
        result = service.detect(Path("/tmp/fake.mp4"), 0.0, 5.0)

    # crop_w = int(9/16 * 720) = 405
    # face_center_x = 320, so crop_x = 320 - 202 = 118 (clamped to >=0)
    assert result.face_detected is True
    assert result.crop_w == 405
    assert result.crop_h == 720
    assert result.crop_x >= 0
    assert result.crop_x + result.crop_w <= 1280


def test_speaker_detection_falls_back_to_center_when_no_face() -> None:
    service = SpeakerDetectionService()
    no_face = MagicMock()
    no_face.detections = []
    with (
        patch("cv2.VideoCapture", return_value=_make_mock_cap(width=1280, height=720)),
        patch("mediapipe.solutions.face_detection.FaceDetection") as mock_fd,
    ):
        mock_fd.return_value.__enter__.return_value.process.return_value = no_face
        result = service.detect(Path("/tmp/fake.mp4"), 0.0, 5.0)

    assert result.face_detected is False
    assert result.confidence == 0.0
    # Center crop: crop_x = (1280 - 405) // 2 = 437
    assert result.crop_x == (1280 - 405) // 2


def test_speaker_crop_result_crop_x_clamped_to_valid_range() -> None:
    """Face at far right should not produce a crop that exceeds frame width."""
    service = SpeakerDetectionService(sample_every_n_frames=1)
    with (
        patch("cv2.VideoCapture", return_value=_make_mock_cap(width=1280, height=720)),
        patch("mediapipe.solutions.face_detection.FaceDetection") as mock_fd,
    ):
        # Face at 95% relative → x=1216, very close to right edge
        mock_fd.return_value.__enter__.return_value.process.return_value = (
            _make_face_detection_result(0.95)
        )
        result = service.detect(Path("/tmp/fake.mp4"), 0.0, 5.0)

    assert result.crop_x + result.crop_w <= 1280
    assert result.crop_x >= 0
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_speaker_detection.py -v
```

Expected: `ModuleNotFoundError: No module named '***REMOVED***.services.media.speaker_detection'`

- [ ] **Step 3: Create SpeakerDetectionService**

Create `***REMOVED***/services/media/speaker_detection.py`:

```python
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("***REMOVED***.media.speaker_detection")


@dataclass
class SpeakerCropResult:
    crop_x: int
    crop_w: int
    crop_h: int
    confidence: float  # fraction of sampled frames where a face was detected
    face_detected: bool  # False means fell back to center crop


class SpeakerDetectionService:
    """Detects speaker position in a video clip and returns a stable 9:16 crop window.

    Uses mediapipe face detection, sampling every N frames for efficiency.
    Returns the median face X position across sampled frames to avoid jitter.
    Falls back to center crop when no face is detected.
    """

    def __init__(self, sample_every_n_frames: int = 5) -> None:
        self.sample_every_n_frames = sample_every_n_frames

    def detect(
        self,
        video_path: Path,
        start_sec: float,
        end_sec: float,
    ) -> SpeakerCropResult:
        import cv2
        import mediapipe as mp

        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        crop_w = int(9 / 16 * src_h)
        crop_h = src_h
        center_x = max(0, (src_w - crop_w) // 2)

        start_frame = int(start_sec * fps)
        end_frame = int(end_sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        face_x_positions: list[float] = []
        total_sampled = 0
        frame_idx = start_frame

        mp_face = mp.solutions.face_detection
        with mp_face.FaceDetection(min_detection_confidence=0.5) as detector:
            while cap.isOpened() and frame_idx <= end_frame:
                ret, frame = cap.read()
                if not ret:
                    break
                if (frame_idx - start_frame) % self.sample_every_n_frames == 0:
                    total_sampled += 1
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = detector.process(rgb)
                    if results.detections:
                        bbox = results.detections[0].location_data.relative_bounding_box
                        face_center_x = (bbox.xmin + bbox.width / 2) * src_w
                        face_x_positions.append(face_center_x)
                frame_idx += 1

        cap.release()

        if not face_x_positions:
            logger.info(
                "No face detected — falling back to center crop",
                extra={"video_path": str(video_path), "total_sampled": total_sampled},
            )
            return SpeakerCropResult(
                crop_x=center_x,
                crop_w=crop_w,
                crop_h=crop_h,
                confidence=0.0,
                face_detected=False,
            )

        median_face_x = statistics.median(face_x_positions)
        crop_x = int(median_face_x) - crop_w // 2
        crop_x = max(0, min(crop_x, src_w - crop_w))
        confidence = len(face_x_positions) / total_sampled if total_sampled > 0 else 0.0

        logger.info(
            "Speaker detected",
            extra={
                "video_path": str(video_path),
                "median_face_x": median_face_x,
                "crop_x": crop_x,
                "confidence": confidence,
                "frames_sampled": total_sampled,
                "faces_found": len(face_x_positions),
            },
        )
        return SpeakerCropResult(
            crop_x=crop_x,
            crop_w=crop_w,
            crop_h=crop_h,
            confidence=confidence,
            face_detected=True,
        )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_speaker_detection.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/services/media/speaker_detection.py ***REMOVED***/clipping/tests/test_speaker_detection.py
git commit -m "feat(media): add SpeakerDetectionService with mediapipe face detection"
```

---

## Task 6: ClipRenderer — SMART_CROP Mode

**Files:**
- Modify: `***REMOVED***/services/media/clip_renderer.py`
- Modify: `***REMOVED***/clipping/tests/test_renderer.py`

- [ ] **Step 1: Write failing tests**

Add to `***REMOVED***/clipping/tests/test_renderer.py`:

```python
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from ***REMOVED***.clipping.constants import RenderMode
from ***REMOVED***.services.media.speaker_detection import SpeakerCropResult


@pytest.mark.django_db
def test_clip_renderer_smart_crop_with_manual_override_uses_given_coords() -> None:
    from ***REMOVED***.clipping.tests.factories import ClipLayoutConfigFactory

    layout = ClipLayoutConfigFactory(
        render_mode=RenderMode.SMART_CROP,
        manual_crop_x=200,
        manual_crop_y=0,
        manual_crop_w=405,
        manual_crop_h=720,
    )
    config = ClipRenderConfig(
        source_path=Path("/tmp/source.mp4"),
        output_path=Path("/tmp/output.mp4"),
        start_sec=0.0,
        end_sec=60.0,
        layout_config=layout,
    )
    renderer = ClipRenderer(config)
    args = renderer._build_ffmpeg_command()

    assert "crop=405:720:200:0" in " ".join(args)
    assert "scale=1080:1920" in " ".join(args)


@pytest.mark.django_db
def test_clip_renderer_smart_crop_auto_calls_speaker_detection() -> None:
    from ***REMOVED***.clipping.tests.factories import ClipLayoutConfigFactory

    layout = ClipLayoutConfigFactory(
        render_mode=RenderMode.SMART_CROP,
        manual_crop_x=None,
        manual_crop_y=None,
        manual_crop_w=None,
        manual_crop_h=None,
    )
    mock_result = SpeakerCropResult(
        crop_x=150, crop_w=405, crop_h=720, confidence=0.8, face_detected=True
    )
    config = ClipRenderConfig(
        source_path=Path("/tmp/source.mp4"),
        output_path=Path("/tmp/output.mp4"),
        start_sec=0.0,
        end_sec=60.0,
        layout_config=layout,
    )
    renderer = ClipRenderer(config)

    with patch(
        "***REMOVED***.services.media.clip_renderer.SpeakerDetectionService.detect",
        return_value=mock_result,
    ):
        args = renderer._build_ffmpeg_command()

    assert "crop=405:720:150:0" in " ".join(args)
    assert renderer.last_speaker_crop_result is mock_result


@pytest.mark.django_db
def test_clip_renderer_none_layout_config_uses_center_crop() -> None:
    config = ClipRenderConfig(
        source_path=Path("/tmp/source.mp4"),
        output_path=Path("/tmp/output.mp4"),
        start_sec=0.0,
        end_sec=60.0,
        layout_config=None,
    )
    renderer = ClipRenderer(config)
    args = renderer._build_ffmpeg_command()
    assert "crop=ih*9/16:ih" in " ".join(args)


@pytest.mark.django_db
def test_clip_renderer_center_crop_mode_uses_center_crop() -> None:
    from ***REMOVED***.clipping.tests.factories import ClipLayoutConfigFactory

    layout = ClipLayoutConfigFactory(render_mode=RenderMode.CENTER_CROP)
    config = ClipRenderConfig(
        source_path=Path("/tmp/source.mp4"),
        output_path=Path("/tmp/output.mp4"),
        start_sec=0.0,
        end_sec=60.0,
        layout_config=layout,
    )
    renderer = ClipRenderer(config)
    args = renderer._build_ffmpeg_command()
    assert "crop=ih*9/16:ih" in " ".join(args)
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_renderer.py -k "smart_crop or none_layout or center_crop_mode" -v
```

Expected: tests fail — `ClipRenderConfig` doesn't accept `layout_config`.

- [ ] **Step 3: Update clip_renderer.py**

Replace the full contents of `***REMOVED***/services/media/clip_renderer.py`:

```python
from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import ffmpeg

if TYPE_CHECKING:
    from ***REMOVED***.clipping.models import ClipLayoutConfig
    from ***REMOVED***.services.media.speaker_detection import SpeakerCropResult

logger = logging.getLogger("***REMOVED***.media.clip_renderer")


@dataclass
class ClipRenderConfig:
    source_path: Path
    output_path: Path
    start_sec: float
    end_sec: float
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = "slow"
    audio_bitrate: str = "192k"
    include_captions: bool = True
    include_title_card: bool = True
    include_branding: bool = True
    hook_text: str = ""
    transcript_json: dict[str, Any] = field(default_factory=dict)
    intro_path: Path | None = None
    outro_path: Path | None = None
    layout_config: ClipLayoutConfig | None = None


class ClipRenderer:
    def __init__(self, config: ClipRenderConfig) -> None:
        self.config = config
        # Populated after render() when SMART_CROP auto-detection runs
        self.last_speaker_crop_result: SpeakerCropResult | None = None

    def render(self) -> Path:
        logger.info(
            "Starting clip render",
            extra={
                "source": str(self.config.source_path),
                "output": str(self.config.output_path),
                "start_sec": self.config.start_sec,
                "end_sec": self.config.end_sec,
            },
        )

        probe = ffmpeg.probe(str(self.config.source_path))
        if not probe:
            msg = f"Cannot probe source file: {self.config.source_path}"
            raise ValueError(msg)

        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)

        start_time = time.perf_counter()
        cmd = self._build_ffmpeg_command()
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr}")

        elapsed = time.perf_counter() - start_time
        logger.info(
            "Clip render completed",
            extra={
                "output": str(self.config.output_path),
                "render_duration_sec": elapsed,
            },
        )
        return self.config.output_path

    def _build_ffmpeg_command(self) -> list[str]:
        lc = self.config.layout_config
        mode = lc.render_mode if lc else "CENTER_CROP"

        if mode == "SPATIAL_STACK":
            return self._build_spatial_stack_command(lc)  # type: ignore[arg-type]

        vf = (
            self._build_smart_crop_filter(lc)  # type: ignore[arg-type]
            if mode == "SMART_CROP"
            else self._build_center_crop_filter()
        )
        c = self.config
        return [
            "ffmpeg",
            "-y",
            "-ss", str(c.start_sec),
            "-to", str(c.end_sec),
            "-i", str(c.source_path),
            "-vf", vf,
            "-c:v", "libx264",
            "-crf", str(c.crf),
            "-preset", c.preset,
            "-c:a", "aac",
            "-b:a", c.audio_bitrate,
            "-movflags", "faststart",
            str(c.output_path),
        ]

    def _build_center_crop_filter(self) -> str:
        c = self.config
        return f"crop=ih*9/16:ih,scale={c.width}:{c.height},fps={c.fps}"

    def _build_smart_crop_filter(self, lc: ClipLayoutConfig) -> str:
        c = self.config
        if lc.has_manual_smart_crop:
            crop_x = lc.manual_crop_x
            crop_y = lc.manual_crop_y
            crop_w = lc.manual_crop_w
            crop_h = lc.manual_crop_h
        else:
            from ***REMOVED***.services.media.speaker_detection import SpeakerDetectionService

            service = SpeakerDetectionService()
            result = service.detect(c.source_path, c.start_sec, c.end_sec)
            self.last_speaker_crop_result = result
            crop_x = result.crop_x
            crop_y = 0
            crop_w = result.crop_w
            crop_h = result.crop_h
        return f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={c.width}:{c.height},fps={c.fps}"

    def _build_spatial_stack_command(self, lc: ClipLayoutConfig) -> list[str]:
        c = self.config
        top_h = int(c.height * lc.stack_ratio)
        bot_h = c.height - top_h
        filter_complex = (
            f"[0:v]crop={lc.region_a_w}:{lc.region_a_h}:{lc.region_a_x}:{lc.region_a_y},"
            f"scale={c.width}:{top_h}[top];"
            f"[0:v]crop={lc.region_b_w}:{lc.region_b_h}:{lc.region_b_x}:{lc.region_b_y},"
            f"scale={c.width}:{bot_h}[bot];"
            f"[top][bot]vstack=inputs=2[out]"
        )
        return [
            "ffmpeg",
            "-y",
            "-ss", str(c.start_sec),
            "-to", str(c.end_sec),
            "-i", str(c.source_path),
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a",
            "-c:v", "libx264",
            "-crf", str(c.crf),
            "-preset", c.preset,
            "-c:a", "aac",
            "-b:a", c.audio_bitrate,
            "-movflags", "faststart",
            str(c.output_path),
        ]

    def get_output_duration(self) -> float:
        if not self.config.output_path.exists():
            return 0.0
        probe = ffmpeg.probe(str(self.config.output_path))
        return float(probe["format"]["duration"])
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_renderer.py -v
```

Expected: all tests pass including the original three.

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/services/media/clip_renderer.py ***REMOVED***/clipping/tests/test_renderer.py
git commit -m "feat(media): add SMART_CROP and layout_config support to ClipRenderer"
```

---

## Task 7: ClipRenderer — SPATIAL_STACK Mode

**Files:**
- Modify: `***REMOVED***/clipping/tests/test_renderer.py`

(The `_build_spatial_stack_command` method was already added in Task 6. This task adds its tests.)

- [ ] **Step 1: Write tests**

Add to `***REMOVED***/clipping/tests/test_renderer.py`:

```python
@pytest.mark.django_db
def test_clip_renderer_spatial_stack_uses_filter_complex() -> None:
    from ***REMOVED***.clipping.tests.factories import ClipLayoutConfigFactory

    layout = ClipLayoutConfigFactory(
        render_mode=RenderMode.SPATIAL_STACK,
        region_a_x=0, region_a_y=0, region_a_w=400, region_a_h=300,
        region_b_x=880, region_b_y=420, region_b_w=400, region_b_h=300,
        stack_ratio=0.6,
    )
    config = ClipRenderConfig(
        source_path=Path("/tmp/source.mp4"),
        output_path=Path("/tmp/output.mp4"),
        start_sec=0.0,
        end_sec=60.0,
        layout_config=layout,
    )
    renderer = ClipRenderer(config)
    args = renderer._build_ffmpeg_command()

    # Must use filter_complex
    assert "-filter_complex" in args
    fc_index = args.index("-filter_complex")
    filter_complex = args[fc_index + 1]

    # Region A crop
    assert "crop=400:300:0:0" in filter_complex
    # Region B crop
    assert "crop=400:300:880:420" in filter_complex
    # vstack
    assert "vstack=inputs=2" in filter_complex
    # Output mapped
    assert "[out]" in args


@pytest.mark.django_db
def test_clip_renderer_spatial_stack_respects_stack_ratio() -> None:
    from ***REMOVED***.clipping.tests.factories import ClipLayoutConfigFactory

    layout = ClipLayoutConfigFactory(
        render_mode=RenderMode.SPATIAL_STACK,
        region_a_x=0, region_a_y=0, region_a_w=400, region_a_h=300,
        region_b_x=880, region_b_y=420, region_b_w=400, region_b_h=300,
        stack_ratio=0.7,
    )
    config = ClipRenderConfig(
        source_path=Path("/tmp/source.mp4"),
        output_path=Path("/tmp/output.mp4"),
        start_sec=0.0,
        end_sec=60.0,
        height=1920,
        layout_config=layout,
    )
    renderer = ClipRenderer(config)
    args = renderer._build_ffmpeg_command()

    fc_index = args.index("-filter_complex")
    filter_complex = args[fc_index + 1]

    # top_h = int(1920 * 0.7) = 1344, bot_h = 576
    assert "scale=1080:1344[top]" in filter_complex
    assert "scale=1080:576[bot]" in filter_complex
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_renderer.py -k "spatial_stack" -v
```

Expected: both tests pass.

- [ ] **Step 3: Commit**

```bash
git add ***REMOVED***/clipping/tests/test_renderer.py
git commit -m "test(media): add SPATIAL_STACK renderer tests"
```

---

## Task 8: preview_clip_layout Task

**Files:**
- Modify: `***REMOVED***/clipping/tasks.py`

- [ ] **Step 1: Write failing test**

Create `***REMOVED***/clipping/tests/test_tasks.py` (or add to it if it exists):

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import numpy as np
import pytest

from ***REMOVED***.clipping.tests.factories import ClipCandidateFactory
from ***REMOVED***.clipping.tests.factories import ClipLayoutConfigFactory


@pytest.mark.django_db
def test_preview_clip_layout_saves_preview_image(settings, tmp_path) -> None:
    settings.MEDIA_ROOT = str(tmp_path)

    candidate = ClipCandidateFactory(start_sec=10.0, end_sec=70.0)
    layout = ClipLayoutConfigFactory(
        candidate=candidate,
        render_mode="SMART_CROP",
        manual_crop_x=100,
        manual_crop_y=0,
        manual_crop_w=405,
        manual_crop_h=720,
    )
    # Simulate a downloaded file existing
    fake_video = tmp_path / "clipping" / "downloaded" / f"{candidate.clipping_job.id}.mp4"
    fake_video.parent.mkdir(parents=True, exist_ok=True)
    fake_video.write_bytes(b"fake")
    candidate.clipping_job.downloaded_file = str(fake_video.relative_to(tmp_path))
    candidate.clipping_job.save(update_fields=["downloaded_file", "updated_at"])

    black_frame = np.zeros((720, 1280, 3), dtype="uint8")
    mock_cap = MagicMock()
    mock_cap.read.return_value = (True, black_frame)

    with (
        patch("cv2.VideoCapture", return_value=mock_cap),
        patch("cv2.cvtColor", return_value=black_frame),
    ):
        from ***REMOVED***.clipping.tasks import preview_clip_layout

        preview_clip_layout(str(candidate.id))

    layout.refresh_from_db()
    assert layout.preview_image.name  # file path was saved
    preview_path = tmp_path / layout.preview_image.name
    assert preview_path.exists()
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_tasks.py::test_preview_clip_layout_saves_preview_image -v
```

Expected: `ImportError` — `preview_clip_layout` doesn't exist yet.

- [ ] **Step 3: Add preview_clip_layout to tasks.py**

Add these imports at the top of `***REMOVED***/clipping/tasks.py`:

```python
from PIL import Image
from PIL import ImageDraw
```

Add the new task after the existing `sync_clip_analytics` task:

```python
@shared_task(
    bind=True,
    name="***REMOVED***.clipping.preview_clip_layout",
    queue="clipping",
)
def preview_clip_layout(self, candidate_id: str) -> None:
    """Extract a frame from the clip and draw crop region overlays as a preview image.

    For SMART_CROP with no manual override, runs face detection to show where
    the auto-crop would land. Saves the result to ClipLayoutConfig.preview_image.
    """
    import cv2

    try:
        candidate = ClipCandidate.objects.select_related(
            "layout_config",
            "clipping_job",
        ).get(id=candidate_id)
    except ClipCandidate.DoesNotExist:
        logger.error("ClipCandidate not found for preview", extra={"id": candidate_id})
        return

    lc = getattr(candidate, "layout_config", None)
    if lc is None:
        logger.warning("No layout_config on candidate", extra={"candidate_id": candidate_id})
        return

    if not candidate.clipping_job.downloaded_file:
        logger.warning(
            "No downloaded file for preview",
            extra={"candidate_id": candidate_id},
        )
        return

    video_path = Path(settings.MEDIA_ROOT) / candidate.clipping_job.downloaded_file.name
    midpoint = (candidate.start_sec + candidate.end_sec) / 2

    cap = cv2.VideoCapture(str(video_path))
    cap.set(cv2.CAP_PROP_POS_MSEC, midpoint * 1000)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        logger.warning(
            "Could not extract frame for preview",
            extra={"candidate_id": candidate_id, "midpoint": midpoint},
        )
        return

    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(frame_rgb)
    draw = ImageDraw.Draw(img)

    if lc.render_mode == "SMART_CROP":
        if lc.has_manual_smart_crop:
            x = lc.manual_crop_x
            y = lc.manual_crop_y
            w = lc.manual_crop_w
            h = lc.manual_crop_h
        else:
            from ***REMOVED***.services.media.speaker_detection import SpeakerDetectionService

            service = SpeakerDetectionService()
            result = service.detect(video_path, candidate.start_sec, candidate.end_sec)
            x, y, w, h = result.crop_x, 0, result.crop_w, result.crop_h
        draw.rectangle([x, y, x + w, y + h], outline="green", width=4)

    elif lc.render_mode == "SPATIAL_STACK":
        if lc.region_a_x is not None:
            ax, ay, aw, ah = lc.region_a_x, lc.region_a_y, lc.region_a_w, lc.region_a_h
            draw.rectangle([ax, ay, ax + aw, ay + ah], outline="blue", width=4)
        if lc.region_b_x is not None:
            bx, by, bw, bh = lc.region_b_x, lc.region_b_y, lc.region_b_w, lc.region_b_h
            draw.rectangle([bx, by, bx + bw, by + bh], outline="orange", width=4)

    output_path = Path(settings.MEDIA_ROOT) / "clipping" / "previews" / f"{candidate_id}.jpg"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), "JPEG")

    lc.preview_image = str(output_path.relative_to(Path(settings.MEDIA_ROOT)))
    lc.save(update_fields=["preview_image", "updated_at"])

    logger.info(
        "Clip layout preview generated",
        extra={"candidate_id": candidate_id, "preview_path": str(output_path)},
    )
```

- [ ] **Step 4: Run test**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_tasks.py::test_preview_clip_layout_saves_preview_image -v
```

Expected: passes.

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/clipping/tasks.py ***REMOVED***/clipping/tests/test_tasks.py
git commit -m "feat(clipping): add preview_clip_layout task with crop region overlay"
```

---

## Task 9: Update render_clip Task

The `render_clip` task needs to pass `layout_config` to `ClipRenderConfig` and write detection quality back after the render.

**Files:**
- Modify: `***REMOVED***/clipping/tasks.py`
- Modify: `***REMOVED***/clipping/tests/test_tasks.py`

- [ ] **Step 1: Write failing test**

Add to `***REMOVED***/clipping/tests/test_tasks.py`:

```python
@pytest.mark.django_db
def test_render_clip_passes_layout_config_to_renderer(settings, tmp_path) -> None:
    settings.MEDIA_ROOT = str(tmp_path)

    candidate = ClipCandidateFactory(start_sec=0.0, end_sec=60.0)
    ClipLayoutConfigFactory(
        candidate=candidate,
        render_mode="CENTER_CROP",
    )
    fake_video = tmp_path / "clipping" / "downloaded" / "source.mp4"
    fake_video.parent.mkdir(parents=True, exist_ok=True)
    fake_video.write_bytes(b"fake")
    candidate.clipping_job.downloaded_file = str(fake_video.relative_to(tmp_path))
    candidate.clipping_job.save(update_fields=["downloaded_file", "updated_at"])

    with patch("***REMOVED***.clipping.tasks.ClipRenderer") as mock_renderer_cls:
        mock_renderer = MagicMock()
        mock_renderer.render.return_value = tmp_path / "output.mp4"
        mock_renderer.last_speaker_crop_result = None
        mock_renderer_cls.return_value = mock_renderer

        from ***REMOVED***.clipping.tasks import render_clip

        render_clip(str(candidate.id))

    call_kwargs = mock_renderer_cls.call_args[0][0]  # first positional arg = ClipRenderConfig
    assert call_kwargs.layout_config is not None
    assert call_kwargs.layout_config.render_mode == "CENTER_CROP"


@pytest.mark.django_db
def test_render_clip_writes_detection_confidence_back(settings, tmp_path) -> None:
    settings.MEDIA_ROOT = str(tmp_path)

    from ***REMOVED***.services.media.speaker_detection import SpeakerCropResult

    candidate = ClipCandidateFactory(start_sec=0.0, end_sec=60.0)
    layout = ClipLayoutConfigFactory(candidate=candidate, render_mode="SMART_CROP")
    fake_video = tmp_path / "clipping" / "downloaded" / "source.mp4"
    fake_video.parent.mkdir(parents=True, exist_ok=True)
    fake_video.write_bytes(b"fake")
    candidate.clipping_job.downloaded_file = str(fake_video.relative_to(tmp_path))
    candidate.clipping_job.save(update_fields=["downloaded_file", "updated_at"])

    mock_result = SpeakerCropResult(
        crop_x=150, crop_w=405, crop_h=720, confidence=0.85, face_detected=True
    )

    with patch("***REMOVED***.clipping.tasks.ClipRenderer") as mock_renderer_cls:
        mock_renderer = MagicMock()
        mock_renderer.render.return_value = tmp_path / "output.mp4"
        mock_renderer.last_speaker_crop_result = mock_result
        mock_renderer_cls.return_value = mock_renderer

        from ***REMOVED***.clipping.tasks import render_clip

        render_clip(str(candidate.id))

    layout.refresh_from_db()
    assert layout.face_detected is True
    assert abs(layout.detection_confidence - 0.85) < 0.001
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_tasks.py -k "render_clip" -v
```

Expected: tests fail — `render_clip` doesn't pass `layout_config`.

- [ ] **Step 3: Update render_clip in tasks.py**

First, move `ClipRenderer` and `ClipRenderConfig` to top-level imports in `***REMOVED***/clipping/tasks.py`. Find the two lazy import lines inside the `render_clip` try block:

```python
        from ***REMOVED***.services.media.clip_renderer import ClipRenderConfig
        from ***REMOVED***.services.media.clip_renderer import ClipRenderer
```

Delete those two lines and add them at the top of the file with the other imports:

```python
from ***REMOVED***.services.media.clip_renderer import ClipRenderConfig
from ***REMOVED***.services.media.clip_renderer import ClipRenderer
```

Then replace the entire `render_clip` body — from the first `try:` (the `ClipCandidate.objects.get`) through the end of the `except Exception` block — with:

```python
    try:
        candidate = ClipCandidate.objects.select_related(
            "layout_config",
            "clipping_job__channel",
        ).get(id=clip_candidate_id)
    except ClipCandidate.DoesNotExist:
        logger.error("ClipCandidate not found", extra={"id": clip_candidate_id})
        return

    render = ClipRender.objects.create(
        candidate=candidate,
        format=ClipRender.Format.VERTICAL_9_16,
        celery_task_id=self.request.id,
        status=ClipRender.RenderStatus.RUNNING,
    )

    try:
        job = candidate.clipping_job
        channel = job.channel
        layout_config = getattr(candidate, "layout_config", None)

        source_path = Path(settings.MEDIA_ROOT) / job.downloaded_file.name
        output_path = get_clip_render_path(str(candidate.id), render.format)

        config = ClipRenderConfig(
            source_path=source_path,
            output_path=output_path,
            start_sec=candidate.start_sec,
            end_sec=candidate.end_sec,
            hook_text=candidate.hook_text if render.include_title_card else "",
            transcript_json=job.transcript_json if render.include_captions else {},
            intro_path=Path(channel.channel_intro_file.path) if channel.channel_intro_file else None,
            outro_path=Path(channel.channel_outro_file.path) if channel.channel_outro_file else None,
            layout_config=layout_config,
        )

        renderer = ClipRenderer(config)
        renderer.render()

        # Write speaker detection quality back to layout_config for admin visibility
        if (
            layout_config is not None
            and layout_config.render_mode == "SMART_CROP"
            and renderer.last_speaker_crop_result is not None
        ):
            detection = renderer.last_speaker_crop_result
            layout_config.face_detected = detection.face_detected
            layout_config.detection_confidence = detection.confidence
            layout_config.save(update_fields=["face_detected", "detection_confidence", "updated_at"])

        render.video_file = str(output_path.relative_to(settings.MEDIA_ROOT))
        render.file_size_bytes = output_path.stat().st_size
        render.status = ClipRender.RenderStatus.COMPLETED
        render.save(update_fields=["video_file", "file_size_bytes", "status", "updated_at"])

        candidate.status = ClipCandidate.CandidateStatus.RENDERED
        candidate.save(update_fields=["status", "updated_at"])

        for account in job.target_accounts.filter(is_active=True, should_post=True):
            post = ClipPost.objects.create(render=render, social_account=account)
            post_clip.delay(str(post.id))

    except Exception as exc:
        render.status = ClipRender.RenderStatus.FAILED
        render.last_error = str(exc)
        render.save(update_fields=["status", "last_error", "updated_at"])
        raise self.retry(exc=exc, countdown=2**self.request.retries * 300)
```

**Note:** The patch path `***REMOVED***.clipping.tasks.ClipRenderer` in the tests works only after moving the import to the top of tasks.py (done above). If the import stays lazy inside the try block, the patch cannot intercept it.

- [ ] **Step 4: Run tests**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_tasks.py -k "render_clip" -v
```

Expected: both new tests pass.

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest ***REMOVED***/clipping/tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add ***REMOVED***/clipping/tasks.py ***REMOVED***/clipping/tests/test_tasks.py
git commit -m "feat(clipping): pass layout_config to renderer and write detection quality back"
```

---

## Task 10: Admin

Add `ClipLayoutConfigInline` to `ClipCandidateAdmin`, a "Generate Preview" action, and a "Default Clip Layout" fieldset to `ChannelAdmin`.

**Files:**
- Modify: `***REMOVED***/clipping/admin.py`
- Modify: `***REMOVED***/channels/admin.py`

- [ ] **Step 1: Update clipping/admin.py**

Add this import at the top of `***REMOVED***/clipping/admin.py` with the existing model imports:

```python
from ***REMOVED***.clipping.models import ClipLayoutConfig
```

Add `ClipLayoutConfigInline` after `ClipRenderInline`:

```python
class ClipLayoutConfigInline(StackedInline):
    model = ClipLayoutConfig
    extra = 0
    can_delete = False
    readonly_fields = ("face_detected", "detection_confidence", "preview_image_display")
    fieldsets = (
        (
            None,
            {"fields": ("render_mode",)},
        ),
        (
            "Smart Crop Override",
            {
                "fields": (
                    ("manual_crop_x", "manual_crop_y"),
                    ("manual_crop_w", "manual_crop_h"),
                    ("face_detected", "detection_confidence"),
                ),
                "description": "Leave all four fields blank to auto-detect via face detection.",
            },
        ),
        (
            "Region A — Top",
            {
                "fields": (
                    "region_a_label",
                    ("region_a_x", "region_a_y"),
                    ("region_a_w", "region_a_h"),
                ),
            },
        ),
        (
            "Region B — Bottom",
            {
                "fields": (
                    "region_b_label",
                    ("region_b_x", "region_b_y"),
                    ("region_b_w", "region_b_h"),
                    "stack_ratio",
                ),
            },
        ),
        (
            "Preview",
            {"fields": ("preview_image_display",)},
        ),
    )

    @display(description="Preview")
    def preview_image_display(self, obj: ClipLayoutConfig) -> str:
        if not obj.preview_image:
            return "—"
        url = obj.preview_image.url
        return format_html(
            '<img src="{}" style="max-width:480px;max-height:270px;border:1px solid #ccc;">',
            url,
        )
```

Update `ClipCandidateAdmin` — add the inline and the action:

```python
@admin.register(ClipCandidate)
class ClipCandidateAdmin(ModelAdmin):
    list_display = (
        "__str__",
        "clipping_job",
        "relevance_score",
        "status",
        "approved",
    )
    list_filter = ("status", "approved")
    search_fields = ("title", "clipping_job__source_title")
    readonly_fields = (
        "id",
        "clipping_job",
        "start_sec",
        "end_sec",
        "title",
        "hook_text",
        "relevance_score",
        "reason",
        "transcript_excerpt",
        "status",
        "approved",
        "approved_at",
        "approved_by",
        "created_at",
        "updated_at",
    )
    inlines = [ClipLayoutConfigInline, ClipRenderInline]
    actions = ["generate_layout_preview"]

    @admin.action(description="Generate layout preview for selected candidates")
    def generate_layout_preview(
        self, request: HttpRequest, queryset
    ) -> None:
        from ***REMOVED***.clipping.tasks import preview_clip_layout

        count = 0
        for candidate in queryset:
            preview_clip_layout.delay(str(candidate.id))
            count += 1
        self.message_user(request, f"Preview generation queued for {count} candidate(s).")
```

Update the `__all__` at the bottom to include the new inline:

```python
__all__ = [
    "ClipCandidateAdmin",
    "ClipCandidateInline",
    "ClipLayoutConfigInline",
    "ClipPostAdmin",
    "ClipRenderInline",
    "ClippingJobAdmin",
]
```

- [ ] **Step 2: Update channels/admin.py**

Add this import at the top of `***REMOVED***/channels/admin.py`:

```python
from ***REMOVED***.clipping.constants import RenderMode as ClipRenderMode
```

In `ChannelAdmin.fieldsets`, add a new "Default Clip Layout" section at the end of the tuple (before the closing parenthesis):

```python
        (
            _("Default Clip Layout"),
            {
                "fields": (
                    "default_render_mode",
                    "default_layout_config",
                ),
                "description": (
                    "Sets the layout applied to new ClipCandidates from this channel. "
                    "SMART_CROP auto-detects the speaker. "
                    "For SPATIAL_STACK, add region coordinates to the JSON field."
                ),
            },
        ),
```

- [ ] **Step 3: Verify admin loads without errors**

```bash
uv run python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 4: Run full test suite**

```bash
uv run pytest ***REMOVED***/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/clipping/admin.py ***REMOVED***/channels/admin.py
git commit -m "feat(admin): add ClipLayoutConfigInline and generate preview action to ClipCandidateAdmin"
```

---

## Final Verification

- [ ] **Run complete test suite**

```bash
uv run pytest ***REMOVED***/ -v
```

Expected: all tests pass with no failures.

- [ ] **Run system check**

```bash
uv run python manage.py check
```

Expected: no issues.

- [ ] **Confirm migrations are clean**

```bash
uv run python manage.py migrate --check
```

Expected: no unapplied migrations.
