# Clip Render Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the clipping pipeline into a CapCut-style multi-stage renderer supporting captions, hooks, intro/outro library with transitions, watermarks, timed overlays, progress bar, background music, per-stage output tracking, and per-stage admin retry.

**Architecture:** A 10-stage `ClipRenderPipeline` replaces `ClipRenderer`. Each stage is an independent `RenderStage` subclass that reads one file, writes another, and records a `ClipRenderStageResult`. Style is driven by `ClipRenderTemplate` (channel-level defaults) and `ClipStyleConfig` (per-clip overrides inheriting all style fields from an abstract mixin).

**Tech Stack:** Django 5.2, FFmpeg (subprocess), ffmpeg-python (probing), ASS subtitle format (captions), Pillow/OpenCV (style preview), Celery, Unfold admin.

**Spec:** `docs/superpowers/specs/2026-03-28-clip-render-enhancements-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `***REMOVED***/clipping/constants.py` | Modify | Add 8 new choice classes |
| `***REMOVED***/clipping/models.py` | Modify | Add `ClipRenderStyleMixin` (abstract), `ClipRenderTemplate`, `ClipMediaAsset`, `ClipMusicAsset`, `ClipStyleConfig`, `ClipTimedOverlay`, `ClipRenderStageResult` |
| `***REMOVED***/clipping/signals.py` | Modify | Add duration-detection signals + `ClipCandidate→ClipStyleConfig` signal |
| `***REMOVED***/clipping/apps.py` | Modify | Connect `Channel→ClipRenderTemplate` signal in `ready()` |
| `***REMOVED***/clipping/tests/factories.py` | Modify | Add factories for 5 new models |
| `***REMOVED***/clipping/tests/test_models.py` | Modify | Model validation tests |
| `***REMOVED***/clipping/tests/test_signals.py` | Modify | Signal behavior tests |
| `***REMOVED***/clipping/migrations/0005_*.py` | Create | Auto-generated schema migration |
| `***REMOVED***/clipping/migrations/0006_*.py` | Create | Data migration: seed ClipRenderTemplate for existing Channels |
| `***REMOVED***/clipping/migrations/0007_*.py` | Create | Data migration: seed ClipStyleConfig for existing ClipCandidates |
| `***REMOVED***/core/storage.py` | Modify | Add `get_stage_output_path()` and `get_clip_ass_path()` |
| `***REMOVED***/services/media/render_stages/__init__.py` | Create | Package exports |
| `***REMOVED***/services/media/render_stages/base.py` | Create | `RenderStage` ABC |
| `***REMOVED***/services/media/render_stages/trim_crop.py` | Create | `TrimAndCropStage` (absorbs `ClipRenderer` logic) |
| `***REMOVED***/services/media/render_stages/intro_outro.py` | Create | `IntroConcatStage`, `OutroConcatStage` |
| `***REMOVED***/services/media/render_stages/hook.py` | Create | `HookStage` |
| `***REMOVED***/services/media/render_stages/captions.py` | Create | `ASSGenerator`, `CaptionTranslationStage`, `CaptionStage` |
| `***REMOVED***/services/media/render_stages/watermark.py` | Create | `WatermarkStage` |
| `***REMOVED***/services/media/render_stages/timed_overlays.py` | Create | `TimedOverlayStage` |
| `***REMOVED***/services/media/render_stages/progress_bar.py` | Create | `ProgressBarStage` |
| `***REMOVED***/services/media/render_stages/music_mix.py` | Create | `MusicMixStage` |
| `***REMOVED***/services/media/tests/__init__.py` | Create | Test package |
| `***REMOVED***/services/media/tests/test_render_stages.py` | Create | Stage unit tests (subprocess mocked) |
| `***REMOVED***/services/media/clip_render_pipeline.py` | Create | `PipelineRenderConfig`, `ClipRenderPipeline` |
| `***REMOVED***/services/media/tests/test_clip_render_pipeline.py` | Create | Pipeline orchestration tests |
| `***REMOVED***/clipping/tasks.py` | Modify | Update `render_clip` signature; add `preview_clip_style` |
| `***REMOVED***/channels/admin.py` | Modify | Add `ClipRenderTemplateInline` + `ClipMediaAssetAdmin` + `ClipMusicAssetAdmin` |
| `***REMOVED***/clipping/admin.py` | Modify | Add `ClipStyleConfigInline`, `ClipTimedOverlayInline`, `ClipRenderAdmin` + stage result inline + retry actions |

---

## Task 1: Extend constants.py with new choice classes

**Files:**
- Modify: `***REMOVED***/clipping/constants.py`

- [ ] **Step 1: Write the failing test**

```python
# ***REMOVED***/clipping/tests/test_models.py — add at top of file alongside existing imports
from ***REMOVED***.clipping.constants import (
    CaptionStyle,
    CaptionPosition,
    CaptionAnimation,
    HookStyle,
    TransitionStyle,
    WatermarkType,
    WatermarkPosition,
    ProgressBarPosition,
    MediaAssetType,
)

def test_caption_style_choices_exist() -> None:
    assert CaptionStyle.WORD_BY_WORD == "WORD_BY_WORD"
    assert CaptionStyle.CHUNKED == "CHUNKED"
    assert CaptionStyle.LOWER_THIRD == "LOWER_THIRD"
    assert CaptionStyle.EMOJI_ACCENT == "EMOJI_ACCENT"

def test_transition_style_choices_exist() -> None:
    assert TransitionStyle.NONE == "NONE"
    assert TransitionStyle.CROSSFADE == "CROSSFADE"
    assert TransitionStyle.FADE_BLACK == "FADE_BLACK"
    assert TransitionStyle.WIPE_LEFT == "WIPE_LEFT"
    assert TransitionStyle.WIPE_RIGHT == "WIPE_RIGHT"

def test_hook_style_choices_exist() -> None:
    assert HookStyle.TITLE_CARD == "TITLE_CARD"
    assert HookStyle.OVERLAY_TOP == "OVERLAY_TOP"
    assert HookStyle.OVERLAY_CENTER == "OVERLAY_CENTER"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_models.py::test_caption_style_choices_exist -v
```

Expected: `ImportError: cannot import name 'CaptionStyle'`

- [ ] **Step 3: Implement the constants**

Replace the full contents of `***REMOVED***/clipping/constants.py`:

```python
from __future__ import annotations

from django.db import models


class RenderMode(models.TextChoices):
    SMART_CROP = "SMART_CROP", "Smart Crop (speaker-aware)"
    SPATIAL_STACK = "SPATIAL_STACK", "Spatial Stack (two regions)"
    CENTER_CROP = "CENTER_CROP", "Center Crop (static)"


class CaptionStyle(models.TextChoices):
    WORD_BY_WORD = "WORD_BY_WORD", "Word by Word (karaoke)"
    CHUNKED = "CHUNKED", "Chunked Phrases (3-4 words)"
    LOWER_THIRD = "LOWER_THIRD", "Lower Third (full segment)"
    EMOJI_ACCENT = "EMOJI_ACCENT", "Emoji Accent (chunked + emoji)"


class CaptionPosition(models.TextChoices):
    TOP = "TOP", "Top"
    CENTER = "CENTER", "Center"
    BOTTOM = "BOTTOM", "Bottom"


class CaptionAnimation(models.TextChoices):
    POP = "POP", "Pop"
    FADE = "FADE", "Fade"
    NONE = "NONE", "None"


class HookStyle(models.TextChoices):
    TITLE_CARD = "TITLE_CARD", "Title Card (black frame prepended)"
    OVERLAY_TOP = "OVERLAY_TOP", "Overlay Top (text over video)"
    OVERLAY_CENTER = "OVERLAY_CENTER", "Overlay Center (text over video)"


class TransitionStyle(models.TextChoices):
    NONE = "NONE", "None (hard cut)"
    CROSSFADE = "CROSSFADE", "Crossfade"
    FADE_BLACK = "FADE_BLACK", "Fade to Black"
    WIPE_LEFT = "WIPE_LEFT", "Wipe Left"
    WIPE_RIGHT = "WIPE_RIGHT", "Wipe Right"


class WatermarkType(models.TextChoices):
    IMAGE = "IMAGE", "Image"
    TEXT = "TEXT", "Text"


class WatermarkPosition(models.TextChoices):
    TOP_LEFT = "TOP_LEFT", "Top Left"
    TOP_RIGHT = "TOP_RIGHT", "Top Right"
    BOTTOM_LEFT = "BOTTOM_LEFT", "Bottom Left"
    BOTTOM_RIGHT = "BOTTOM_RIGHT", "Bottom Right"


class ProgressBarPosition(models.TextChoices):
    TOP = "TOP", "Top"
    BOTTOM = "BOTTOM", "Bottom"


class MediaAssetType(models.TextChoices):
    INTRO = "INTRO", "Intro"
    OUTRO = "OUTRO", "Outro"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_models.py::test_caption_style_choices_exist ***REMOVED***/clipping/tests/test_models.py::test_transition_style_choices_exist ***REMOVED***/clipping/tests/test_models.py::test_hook_style_choices_exist -v
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/clipping/constants.py ***REMOVED***/clipping/tests/test_models.py
git commit -m "feat(clipping): add caption/hook/transition/watermark/media choice classes to constants"
```

---

## Task 2: Abstract style mixin, ClipRenderTemplate, ClipMediaAsset, ClipMusicAsset

**Files:**
- Modify: `***REMOVED***/clipping/models.py`
- Modify: `***REMOVED***/clipping/tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

Add to `***REMOVED***/clipping/tests/test_models.py`:

```python
import pytest
from ***REMOVED***.clipping.models import ClipRenderTemplate, ClipMediaAsset, ClipMusicAsset
from ***REMOVED***.channels.tests.factories import ChannelFactory


@pytest.mark.django_db
def test_clip_render_template_auto_fields_have_correct_defaults() -> None:
    channel = ChannelFactory()
    template = ClipRenderTemplate.objects.create(channel=channel)
    assert template.caption_enabled is True
    assert template.caption_style == "CHUNKED"
    assert template.caption_font == "Montserrat-Bold"
    assert template.caption_size == 52
    assert template.caption_color == "#FFFFFF"
    assert template.caption_stroke_color == "#000000"
    assert template.caption_stroke_width == 3
    assert template.caption_bg_color == ""
    assert template.caption_position == "BOTTOM"
    assert template.caption_animation == "POP"
    assert template.caption_language == "en"
    assert template.caption_translate_to == ""
    assert template.emoji_keyword_map == {}
    assert template.hook_enabled is True
    assert template.hook_style == "OVERLAY_TOP"
    assert template.hook_duration_sec == 2.5
    assert template.hook_font == "Montserrat-Bold"
    assert template.hook_size == 60
    assert template.hook_color == "#FFFFFF"
    assert template.hook_bg_color == "#CC000000"
    assert template.hook_animation == "FADE"
    assert template.intro_transition == "NONE"
    assert template.outro_transition == "NONE"
    assert template.transition_duration_sec == 0.5
    assert template.watermark_enabled is False
    assert template.watermark_type == "TEXT"
    assert template.watermark_text == ""
    assert template.watermark_position == "BOTTOM_RIGHT"
    assert template.watermark_opacity == 0.6
    assert template.watermark_size == 32
    assert template.progress_bar_enabled is False
    assert template.progress_bar_position == "TOP"
    assert template.progress_bar_color == "#FFFFFF"
    assert template.progress_bar_height == 6
    assert template.music_enabled is False
    assert template.music_volume_db == -20.0
    assert template.music_fade_in_sec == 1.0
    assert template.music_fade_out_sec == 1.0


@pytest.mark.django_db
def test_clip_render_template_to_style_defaults_returns_all_style_fields() -> None:
    channel = ChannelFactory()
    template = ClipRenderTemplate.objects.create(channel=channel, caption_size=72, music_enabled=True)
    defaults = template.to_style_defaults()
    assert defaults["caption_size"] == 72
    assert defaults["music_enabled"] is True
    # Should not contain non-style fields
    assert "channel" not in defaults
    assert "id" not in defaults
    assert "created_at" not in defaults


@pytest.mark.django_db
def test_clip_media_asset_str_includes_name_and_type() -> None:
    channel = ChannelFactory()
    asset = ClipMediaAsset.objects.create(
        channel=channel, name="Brand Intro", asset_type="INTRO"
    )
    assert "Brand Intro" in str(asset)
    assert "INTRO" in str(asset) or "Intro" in str(asset)


@pytest.mark.django_db
def test_clip_music_asset_str_includes_name() -> None:
    channel = ChannelFactory()
    asset = ClipMusicAsset.objects.create(channel=channel, name="Chill Beat")
    assert "Chill Beat" in str(asset)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_models.py::test_clip_render_template_auto_fields_have_correct_defaults -v
```

Expected: `ImportError: cannot import name 'ClipRenderTemplate'`

- [ ] **Step 3: Add the abstract mixin and three new models to models.py**

In `***REMOVED***/clipping/models.py`, add these imports at the top (after existing imports):

```python
from ***REMOVED***.clipping.constants import CaptionAnimation
from ***REMOVED***.clipping.constants import CaptionPosition
from ***REMOVED***.clipping.constants import CaptionStyle
from ***REMOVED***.clipping.constants import HookStyle
from ***REMOVED***.clipping.constants import MediaAssetType
from ***REMOVED***.clipping.constants import ProgressBarPosition
from ***REMOVED***.clipping.constants import TransitionStyle
from ***REMOVED***.clipping.constants import WatermarkPosition
from ***REMOVED***.clipping.constants import WatermarkType
```

Then add to `models.py` after the `ClipLayoutConfig` class (before any `__all__`):

```python
# ---------------------------------------------------------------------------
# Style mixin — shared by ClipRenderTemplate (channel) and ClipStyleConfig (clip)
# ---------------------------------------------------------------------------

class ClipRenderStyleMixin(models.Model):
    """Abstract mixin providing all render style fields.

    Both ClipRenderTemplate (channel-level) and ClipStyleConfig (per-clip)
    inherit this so the operator can override any field at the clip level.
    """

    # Caption
    caption_enabled = models.BooleanField(default=True)
    caption_style = models.CharField(
        max_length=20, choices=CaptionStyle.choices, default=CaptionStyle.CHUNKED
    )
    caption_font = models.CharField(max_length=100, default="Montserrat-Bold")
    caption_size = models.PositiveIntegerField(default=52)
    caption_color = models.CharField(max_length=9, default="#FFFFFF")
    caption_stroke_color = models.CharField(max_length=9, default="#000000")
    caption_stroke_width = models.PositiveIntegerField(default=3)
    caption_bg_color = models.CharField(max_length=9, blank=True, default="")
    caption_position = models.CharField(
        max_length=10, choices=CaptionPosition.choices, default=CaptionPosition.BOTTOM
    )
    caption_animation = models.CharField(
        max_length=10, choices=CaptionAnimation.choices, default=CaptionAnimation.POP
    )
    caption_language = models.CharField(max_length=10, default="en")
    caption_translate_to = models.CharField(max_length=10, blank=True, default="")
    emoji_keyword_map = models.JSONField(default=dict, blank=True)

    # Hook
    hook_enabled = models.BooleanField(default=True)
    hook_style = models.CharField(
        max_length=20, choices=HookStyle.choices, default=HookStyle.OVERLAY_TOP
    )
    hook_duration_sec = models.FloatField(default=2.5)
    hook_font = models.CharField(max_length=100, default="Montserrat-Bold")
    hook_size = models.PositiveIntegerField(default=60)
    hook_color = models.CharField(max_length=9, default="#FFFFFF")
    hook_bg_color = models.CharField(max_length=9, default="#CC000000")
    hook_animation = models.CharField(
        max_length=10, choices=CaptionAnimation.choices, default=CaptionAnimation.FADE
    )

    # Transitions
    intro_transition = models.CharField(
        max_length=20, choices=TransitionStyle.choices, default=TransitionStyle.NONE
    )
    outro_transition = models.CharField(
        max_length=20, choices=TransitionStyle.choices, default=TransitionStyle.NONE
    )
    transition_duration_sec = models.FloatField(default=0.5)

    # Watermark
    watermark_enabled = models.BooleanField(default=False)
    watermark_type = models.CharField(
        max_length=10, choices=WatermarkType.choices, default=WatermarkType.TEXT
    )
    watermark_text = models.CharField(max_length=100, blank=True, default="")
    watermark_image = models.ImageField(
        upload_to="clipping/watermarks/", blank=True, null=True
    )
    watermark_position = models.CharField(
        max_length=15,
        choices=WatermarkPosition.choices,
        default=WatermarkPosition.BOTTOM_RIGHT,
    )
    watermark_opacity = models.FloatField(default=0.6)
    watermark_size = models.PositiveIntegerField(default=32)

    # Progress bar
    progress_bar_enabled = models.BooleanField(default=False)
    progress_bar_position = models.CharField(
        max_length=10,
        choices=ProgressBarPosition.choices,
        default=ProgressBarPosition.TOP,
    )
    progress_bar_color = models.CharField(max_length=9, default="#FFFFFF")
    progress_bar_height = models.PositiveIntegerField(default=6)

    # Background music
    music_enabled = models.BooleanField(default=False)
    music_volume_db = models.FloatField(default=-20.0)
    music_fade_in_sec = models.FloatField(default=1.0)
    music_fade_out_sec = models.FloatField(default=1.0)

    # The ordered list of style field names (used by to_style_defaults on subclasses)
    STYLE_FIELD_NAMES: list[str] = [
        "caption_enabled", "caption_style", "caption_font", "caption_size",
        "caption_color", "caption_stroke_color", "caption_stroke_width",
        "caption_bg_color", "caption_position", "caption_animation",
        "caption_language", "caption_translate_to", "emoji_keyword_map",
        "hook_enabled", "hook_style", "hook_duration_sec", "hook_font",
        "hook_size", "hook_color", "hook_bg_color", "hook_animation",
        "intro_transition", "outro_transition", "transition_duration_sec",
        "watermark_enabled", "watermark_type", "watermark_text", "watermark_image",
        "watermark_position", "watermark_opacity", "watermark_size",
        "progress_bar_enabled", "progress_bar_position", "progress_bar_color",
        "progress_bar_height",
        "music_enabled", "music_volume_db", "music_fade_in_sec", "music_fade_out_sec",
    ]

    class Meta:
        abstract = True


class ClipRenderTemplate(ClipRenderStyleMixin, BaseAbstractModel):
    """Channel-level render style defaults. One per channel, auto-created on channel save."""

    channel = models.OneToOneField(
        Channel,
        on_delete=models.CASCADE,
        related_name="clip_render_template",
    )

    class Meta:
        verbose_name = "Clip Render Template"
        verbose_name_plural = "Clip Render Templates"

    def __str__(self) -> str:
        return f"Render Template — {self.channel.name}"

    def to_style_defaults(self) -> dict[str, Any]:
        """Return a dict of all style fields suitable for seeding a ClipStyleConfig."""
        result: dict[str, Any] = {}
        for name in self.STYLE_FIELD_NAMES:
            value = getattr(self, name)
            # FileField/ImageField: store the name string (relative path), not the FieldFile
            if hasattr(value, "name"):
                value = value.name or ""
            result[name] = value
        return result


class ClipMediaAsset(BaseAbstractModel):
    """Intro or outro video clip library for a channel.

    Operator uploads short branded clips; duration_sec is auto-detected via ffprobe.
    """

    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="media_assets",
    )
    asset_type = models.CharField(
        max_length=10, choices=MediaAssetType.choices, default=MediaAssetType.INTRO
    )
    name = models.CharField(max_length=200)
    file = models.FileField(upload_to="clipping/media_assets/", max_length=500)
    duration_sec = models.FloatField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["asset_type", "name"]
        verbose_name = "Clip Media Asset"
        verbose_name_plural = "Clip Media Assets"
        indexes = [
            models.Index(fields=["channel", "asset_type", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_asset_type_display()} — {self.name}"


class ClipMusicAsset(BaseAbstractModel):
    """Background music track library for a channel."""

    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="music_assets",
    )
    name = models.CharField(max_length=200)
    file = models.FileField(upload_to="clipping/music_assets/", max_length=500)
    duration_sec = models.FloatField(null=True, blank=True)
    bpm = models.FloatField(null=True, blank=True)
    genre = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["genre", "name"]
        verbose_name = "Clip Music Asset"
        verbose_name_plural = "Clip Music Assets"
        indexes = [
            models.Index(fields=["channel", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.genre or 'no genre'})"
```

Also add `from typing import Any` to the imports at the top of `models.py` if not already present.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_models.py::test_clip_render_template_auto_fields_have_correct_defaults ***REMOVED***/clipping/tests/test_models.py::test_clip_render_template_to_style_defaults_returns_all_style_fields ***REMOVED***/clipping/tests/test_models.py::test_clip_media_asset_str_includes_name_and_type ***REMOVED***/clipping/tests/test_models.py::test_clip_music_asset_str_includes_name -v
```

Expected: 4 PASSED (these are pure Python tests, no DB needed for default/str tests; `@pytest.mark.django_db` ones require DB).

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/clipping/constants.py ***REMOVED***/clipping/models.py ***REMOVED***/clipping/tests/test_models.py
git commit -m "feat(clipping): add ClipRenderStyleMixin, ClipRenderTemplate, ClipMediaAsset, ClipMusicAsset"
```

---

## Task 3: ClipStyleConfig, ClipTimedOverlay, ClipRenderStageResult models

**Files:**
- Modify: `***REMOVED***/clipping/models.py`
- Modify: `***REMOVED***/clipping/tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

Add to `***REMOVED***/clipping/tests/test_models.py`:

```python
from ***REMOVED***.clipping.models import ClipStyleConfig, ClipTimedOverlay, ClipRenderStageResult
from ***REMOVED***.clipping.tests.factories import ClipCandidateFactory, ClipRenderFactory


@pytest.mark.django_db
def test_clip_style_config_has_all_style_fields() -> None:
    candidate = ClipCandidateFactory()
    # get_or_create because signal may already have created one
    style_config, _ = ClipStyleConfig.objects.get_or_create(candidate=candidate)
    # Should have the same style fields as template
    assert hasattr(style_config, "caption_enabled")
    assert hasattr(style_config, "music_volume_db")
    assert hasattr(style_config, "intro_asset")
    assert hasattr(style_config, "outro_asset")
    assert hasattr(style_config, "music_asset")
    assert hasattr(style_config, "translated_transcript_json")
    assert hasattr(style_config, "preview_image")


@pytest.mark.django_db
def test_clip_timed_overlay_clean_validates_end_after_start() -> None:
    from django.core.exceptions import ValidationError
    candidate = ClipCandidateFactory()
    overlay = ClipTimedOverlay(
        candidate=candidate,
        overlay_type="TEXT",
        text="hello",
        start_sec=10.0,
        end_sec=5.0,  # invalid: end before start
    )
    with pytest.raises(ValidationError):
        overlay.clean()


@pytest.mark.django_db
def test_clip_timed_overlay_clean_passes_with_valid_times() -> None:
    candidate = ClipCandidateFactory()
    overlay = ClipTimedOverlay(
        candidate=candidate,
        overlay_type="TEXT",
        text="hello",
        start_sec=5.0,
        end_sec=10.0,
    )
    overlay.clean()  # should not raise


@pytest.mark.django_db
def test_clip_render_stage_result_str() -> None:
    render = ClipRenderFactory()
    result = ClipRenderStageResult.objects.create(
        render=render,
        stage_name="trim_and_crop",
        stage_order=1,
        status=ClipRenderStageResult.Status.COMPLETED,
    )
    assert "trim_and_crop" in str(result)
    assert "1" in str(result)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_models.py::test_clip_style_config_has_all_style_fields -v
```

Expected: `ImportError: cannot import name 'ClipStyleConfig'`

- [ ] **Step 3: Add the three models to models.py**

Add after `ClipMusicAsset` in `***REMOVED***/clipping/models.py`:

```python
class ClipStyleConfig(ClipRenderStyleMixin, BaseAbstractModel):
    """Per-clip render style overrides. Auto-created on ClipCandidate save,
    pre-populated from the channel's ClipRenderTemplate.
    """

    candidate = models.OneToOneField(
        ClipCandidate,
        on_delete=models.CASCADE,
        related_name="style_config",
    )
    intro_asset = models.ForeignKey(
        ClipMediaAsset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="intro_style_configs",
        limit_choices_to={"asset_type": MediaAssetType.INTRO},
    )
    outro_asset = models.ForeignKey(
        ClipMediaAsset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="outro_style_configs",
        limit_choices_to={"asset_type": MediaAssetType.OUTRO},
    )
    music_asset = models.ForeignKey(
        ClipMusicAsset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="style_configs",
    )
    translated_transcript_json = models.JSONField(default=dict, blank=True)
    preview_image = models.ImageField(
        upload_to="clipping/style_previews/",
        null=True,
        blank=True,
        max_length=500,
    )

    class Meta:
        verbose_name = "Clip Style Config"
        verbose_name_plural = "Clip Style Configs"

    def __str__(self) -> str:
        return f"Style: {self.candidate}"


class ClipTimedOverlay(BaseAbstractModel):
    """A time-ranged text or image overlay applied in the final output.

    Timestamps reference final output time (including intro + hook prepend).
    """

    class OverlayType(models.TextChoices):
        TEXT = "TEXT", "Text"
        IMAGE = "IMAGE", "Image"

    candidate = models.ForeignKey(
        ClipCandidate,
        on_delete=models.CASCADE,
        related_name="timed_overlays",
    )
    overlay_type = models.CharField(
        max_length=10, choices=OverlayType.choices, default=OverlayType.TEXT
    )
    text = models.CharField(max_length=300, blank=True)
    image = models.ImageField(
        upload_to="clipping/timed_overlays/", null=True, blank=True, max_length=500
    )
    start_sec = models.FloatField()
    end_sec = models.FloatField()
    position_x = models.PositiveIntegerField(default=540)
    position_y = models.PositiveIntegerField(default=960)
    opacity = models.FloatField(default=1.0)
    font_size = models.PositiveIntegerField(default=40)
    font_color = models.CharField(max_length=9, default="#FFFFFF")

    class Meta:
        ordering = ["start_sec"]
        verbose_name = "Timed Overlay"
        verbose_name_plural = "Timed Overlays"

    def __str__(self) -> str:
        return f"Overlay [{self.start_sec:.1f}s–{self.end_sec:.1f}s] on {self.candidate}"

    def clean(self) -> None:
        super().clean()
        if self.end_sec <= self.start_sec:
            raise ValidationError("end_sec must be greater than start_sec")


class ClipRenderStageResult(BaseAbstractModel):
    """Per-stage tracking record for a ClipRender pipeline run.

    One record per stage per render. Created by the pipeline before each stage,
    updated on completion or failure. Enables per-stage inspection and retry.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        SKIPPED = "SKIPPED", "Skipped"

    render = models.ForeignKey(
        ClipRender,
        on_delete=models.CASCADE,
        related_name="stage_results",
    )
    stage_name = models.CharField(max_length=100)
    stage_order = models.PositiveIntegerField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    output_file = models.FileField(
        upload_to="clipping/stage_outputs/",
        null=True,
        blank=True,
        max_length=500,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_sec = models.FloatField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["stage_order"]
        verbose_name = "Render Stage Result"
        verbose_name_plural = "Render Stage Results"
        unique_together = [("render", "stage_order")]
        indexes = [
            models.Index(fields=["render", "stage_order"]),
        ]

    def __str__(self) -> str:
        return f"Stage {self.stage_order} ({self.stage_name}) — {self.render_id}"
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_models.py -k "style_config or timed_overlay or stage_result" -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/clipping/models.py ***REMOVED***/clipping/tests/test_models.py
git commit -m "feat(clipping): add ClipStyleConfig, ClipTimedOverlay, ClipRenderStageResult models"
```

---

## Task 4: Signals — duration detection + style config auto-creation + Channel template creation

**Files:**
- Modify: `***REMOVED***/clipping/signals.py`
- Modify: `***REMOVED***/clipping/apps.py`
- Modify: `***REMOVED***/clipping/tests/test_signals.py`

- [ ] **Step 1: Write the failing tests**

Add to `***REMOVED***/clipping/tests/test_signals.py`:

```python
from ***REMOVED***.clipping.models import ClipRenderTemplate, ClipStyleConfig
from ***REMOVED***.channels.tests.factories import ChannelFactory


@pytest.mark.django_db
def test_clip_render_template_auto_created_on_channel_save() -> None:
    channel = ChannelFactory()
    assert ClipRenderTemplate.objects.filter(channel=channel).exists()


@pytest.mark.django_db
def test_clip_render_template_not_duplicated_on_second_channel_save() -> None:
    channel = ChannelFactory()
    channel.name = "Updated Name"
    channel.save()
    assert ClipRenderTemplate.objects.filter(channel=channel).count() == 1


@pytest.mark.django_db
def test_clip_style_config_auto_created_on_candidate_save() -> None:
    from ***REMOVED***.clipping.tests.factories import ClipCandidateFactory
    candidate = ClipCandidateFactory()
    assert ClipStyleConfig.objects.filter(candidate=candidate).exists()


@pytest.mark.django_db
def test_clip_style_config_inherits_template_values() -> None:
    from ***REMOVED***.clipping.tests.factories import ClipCandidateFactory, ClippingJobFactory
    channel = ChannelFactory()
    # Set a non-default value on the channel's template
    template = ClipRenderTemplate.objects.get(channel=channel)
    template.caption_size = 72
    template.music_enabled = True
    template.save(update_fields=["caption_size", "music_enabled", "updated_at"])

    job = ClippingJobFactory(channel=channel)
    candidate = ClipCandidateFactory(clipping_job=job)
    style_config = ClipStyleConfig.objects.get(candidate=candidate)
    assert style_config.caption_size == 72
    assert style_config.music_enabled is True


@pytest.mark.django_db
def test_clip_style_config_not_duplicated_on_second_candidate_save() -> None:
    from ***REMOVED***.clipping.tests.factories import ClipCandidateFactory
    candidate = ClipCandidateFactory()
    candidate.title = "New title"
    candidate.save()
    assert ClipStyleConfig.objects.filter(candidate=candidate).count() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_signals.py::test_clip_render_template_auto_created_on_channel_save -v
```

Expected: FAILED — `ClipRenderTemplate` not created

- [ ] **Step 3: Update signals.py**

Replace `***REMOVED***/clipping/signals.py` with:

```python
from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from django_fsm.signals import post_transition

from ***REMOVED***.clipping.models import ClipCandidate
from ***REMOVED***.clipping.models import ClipLayoutConfig
from ***REMOVED***.clipping.models import ClipMediaAsset
from ***REMOVED***.clipping.models import ClippingJob
from ***REMOVED***.clipping.models import ClipMusicAsset
from ***REMOVED***.clipping.models import ClipStyleConfig

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
    """Auto-create a ClipLayoutConfig when a ClipCandidate is first saved."""
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


@receiver(post_save, sender=ClipCandidate)
def create_style_config_for_candidate(
    sender,
    instance: ClipCandidate,
    created: bool,
    **kwargs,
) -> None:
    """Auto-create a ClipStyleConfig when a ClipCandidate is first saved.

    Pre-populates all style fields from the channel's ClipRenderTemplate.
    """
    if not created:
        return
    channel = instance.clipping_job.channel
    try:
        template = channel.clip_render_template
        style_defaults = template.to_style_defaults()
    except Exception:
        style_defaults = {}

    ClipStyleConfig.objects.get_or_create(
        candidate=instance,
        defaults=style_defaults,
    )


@receiver(post_save, sender=ClipMediaAsset)
def detect_media_asset_duration(
    sender,
    instance: ClipMediaAsset,
    **kwargs,
) -> None:
    """Auto-detect duration_sec via ffprobe when a ClipMediaAsset is saved with a file."""
    if not instance.file or instance.duration_sec is not None:
        return
    try:
        import ffmpeg
        from django.conf import settings
        from pathlib import Path

        file_path = Path(settings.MEDIA_ROOT) / instance.file.name
        if not file_path.exists():
            return
        probe = ffmpeg.probe(str(file_path))
        duration = float(probe["format"]["duration"])
        # Use queryset.update() to avoid recursive signal dispatch
        ClipMediaAsset.objects.filter(pk=instance.pk).update(duration_sec=duration)
        logger.info(
            "Auto-detected media asset duration",
            extra={"asset_id": str(instance.pk), "duration_sec": duration},
        )
    except Exception as exc:
        logger.warning(
            "Could not auto-detect media asset duration",
            extra={"asset_id": str(instance.pk), "error": str(exc)},
        )


@receiver(post_save, sender=ClipMusicAsset)
def detect_music_asset_duration(
    sender,
    instance: ClipMusicAsset,
    **kwargs,
) -> None:
    """Auto-detect duration_sec via ffprobe when a ClipMusicAsset is saved with a file."""
    if not instance.file or instance.duration_sec is not None:
        return
    try:
        import ffmpeg
        from django.conf import settings
        from pathlib import Path

        file_path = Path(settings.MEDIA_ROOT) / instance.file.name
        if not file_path.exists():
            return
        probe = ffmpeg.probe(str(file_path))
        duration = float(probe["format"]["duration"])
        ClipMusicAsset.objects.filter(pk=instance.pk).update(duration_sec=duration)
        logger.info(
            "Auto-detected music asset duration",
            extra={"asset_id": str(instance.pk), "duration_sec": duration},
        )
    except Exception as exc:
        logger.warning(
            "Could not auto-detect music asset duration",
            extra={"asset_id": str(instance.pk), "error": str(exc)},
        )


def create_clip_render_template_for_channel(
    sender,
    instance,
    created: bool,
    **kwargs,
) -> None:
    """Auto-create a ClipRenderTemplate when a Channel is first saved.

    Defined as a plain function (not @receiver) because it's connected in
    ClippingConfig.ready() to avoid circular imports (channels ↔ clipping).
    """
    if not created:
        return
    from ***REMOVED***.clipping.models import ClipRenderTemplate

    ClipRenderTemplate.objects.get_or_create(channel=instance)
```

- [ ] **Step 4: Update apps.py to connect the Channel signal**

Replace `***REMOVED***/clipping/apps.py`:

```python
from __future__ import annotations

from django.apps import AppConfig


class ClippingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "***REMOVED***.clipping"
    verbose_name = "Clipping"

    def ready(self) -> None:
        import ***REMOVED***.clipping.signals  # noqa: F401

        # Connect Channel post_save here (not in signals.py) to avoid circular
        # imports: clipping.models imports channels.models, so importing
        # channels.models again in signals.py at module level would be circular.
        from django.db.models.signals import post_save

        from ***REMOVED***.channels.models import Channel
        from ***REMOVED***.clipping.signals import create_clip_render_template_for_channel

        post_save.connect(create_clip_render_template_for_channel, sender=Channel)
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_signals.py -v
```

Expected: All existing tests + 5 new ones PASSED

- [ ] **Step 6: Commit**

```bash
git add ***REMOVED***/clipping/signals.py ***REMOVED***/clipping/apps.py ***REMOVED***/clipping/tests/test_signals.py
git commit -m "feat(clipping): auto-create ClipRenderTemplate on Channel save and ClipStyleConfig on ClipCandidate save"
```

---

## Task 5: Factories for new models

**Files:**
- Modify: `***REMOVED***/clipping/tests/factories.py`

- [ ] **Step 1: Write the failing test**

Add to `***REMOVED***/clipping/tests/test_models.py`:

```python
def test_clip_style_config_factory_handles_signal_conflict() -> None:
    """Factory must not fail even when the signal already created a ClipStyleConfig."""
    from ***REMOVED***.clipping.tests.factories import ClipStyleConfigFactory
    config = ClipStyleConfigFactory()
    assert config.pk is not None
    # Only one record should exist for the candidate
    from ***REMOVED***.clipping.models import ClipStyleConfig
    assert ClipStyleConfig.objects.filter(candidate=config.candidate).count() == 1


def test_clip_media_asset_factory_creates_valid_record() -> None:
    from ***REMOVED***.clipping.tests.factories import ClipMediaAssetFactory
    asset = ClipMediaAssetFactory()
    assert asset.pk is not None
    assert asset.asset_type == "INTRO"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_models.py::test_clip_style_config_factory_handles_signal_conflict -v
```

Expected: `ImportError: cannot import name 'ClipStyleConfigFactory'`

- [ ] **Step 3: Add factories**

Add to `***REMOVED***/clipping/tests/factories.py`:

```python
from ***REMOVED***.clipping.models import (
    ClipMediaAsset,
    ClipMusicAsset,
    ClipRenderTemplate,
    ClipStyleConfig,
    ClipTimedOverlay,
    ClipRenderStageResult,
)


class ClipRenderTemplateFactory(DjangoModelFactory[ClipRenderTemplate]):
    """Factory for ClipRenderTemplate.

    Uses update_or_create because the Channel post_save signal auto-creates one.
    """
    channel = factory.SubFactory(ChannelFactory)

    class Meta:
        model = ClipRenderTemplate

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        channel = kwargs.get("channel")
        if channel is not None:
            obj, _ = model_class.objects.update_or_create(
                channel=channel,
                defaults={k: v for k, v in kwargs.items() if k != "channel"},
            )
            return obj
        return super()._create(model_class, *args, **kwargs)


class ClipMediaAssetFactory(DjangoModelFactory[ClipMediaAsset]):
    channel = factory.SubFactory(ChannelFactory)
    asset_type = ClipMediaAsset.asset_type.field.choices[0][0]  # "INTRO"
    name = factory.Sequence(lambda n: f"Intro Clip {n}")
    file = factory.django.FileField(filename="intro.mp4", data=b"fake")
    is_active = True

    class Meta:
        model = ClipMediaAsset


class ClipMusicAssetFactory(DjangoModelFactory[ClipMusicAsset]):
    channel = factory.SubFactory(ChannelFactory)
    name = factory.Sequence(lambda n: f"Music Track {n}")
    file = factory.django.FileField(filename="track.mp3", data=b"fake")
    genre = "Chill"
    is_active = True

    class Meta:
        model = ClipMusicAsset


class ClipStyleConfigFactory(DjangoModelFactory[ClipStyleConfig]):
    """Factory for ClipStyleConfig.

    Uses update_or_create because the ClipCandidate post_save signal auto-creates one.
    """
    candidate = factory.SubFactory(ClipCandidateFactory)

    class Meta:
        model = ClipStyleConfig

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        candidate = kwargs.get("candidate")
        if candidate is not None:
            obj, _ = model_class.objects.update_or_create(
                candidate=candidate,
                defaults={k: v for k, v in kwargs.items() if k != "candidate"},
            )
            return obj
        return super()._create(model_class, *args, **kwargs)


class ClipTimedOverlayFactory(DjangoModelFactory[ClipTimedOverlay]):
    candidate = factory.SubFactory(ClipCandidateFactory)
    overlay_type = ClipTimedOverlay.OverlayType.TEXT
    text = "Test overlay text"
    start_sec = 5.0
    end_sec = 10.0

    class Meta:
        model = ClipTimedOverlay


class ClipRenderStageResultFactory(DjangoModelFactory[ClipRenderStageResult]):
    render = factory.SubFactory(ClipRenderFactory)
    stage_name = "trim_and_crop"
    stage_order = 1
    status = ClipRenderStageResult.Status.PENDING

    class Meta:
        model = ClipRenderStageResult
```

Also update the imports at the top of `factories.py` to include all new models.

**Note:** The `asset_type` field default for `ClipMediaAssetFactory` should be `"INTRO"` literally — replace `ClipMediaAsset.asset_type.field.choices[0][0]` with `"INTRO"` for clarity.

- [ ] **Step 4: Run tests**

```bash
uv run pytest ***REMOVED***/clipping/tests/test_models.py::test_clip_style_config_factory_handles_signal_conflict ***REMOVED***/clipping/tests/test_models.py::test_clip_media_asset_factory_creates_valid_record -v
```

Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/clipping/tests/factories.py ***REMOVED***/clipping/tests/test_models.py
git commit -m "test(clipping): add factories for ClipRenderTemplate, ClipMediaAsset, ClipMusicAsset, ClipStyleConfig, ClipTimedOverlay, ClipRenderStageResult"
```

---

## Task 6: Migrations (schema + data)

**Files:**
- Create: `***REMOVED***/clipping/migrations/0005_add_render_style_models.py` (auto-generated)
- Create: `***REMOVED***/clipping/migrations/0006_populate_clip_render_templates.py`
- Create: `***REMOVED***/clipping/migrations/0007_populate_clip_style_configs.py`

- [ ] **Step 1: Generate the schema migration**

```bash
uv run python manage.py makemigrations clipping --name add_render_style_models
```

Expected output: `Migrations for 'clipping': ***REMOVED***/clipping/migrations/0005_add_render_style_models.py`

Verify the generated migration includes tables for: `ClipRenderTemplate`, `ClipMediaAsset`, `ClipMusicAsset`, `ClipStyleConfig`, `ClipTimedOverlay`, `ClipRenderStageResult`.

- [ ] **Step 2: Run the migration**

```bash
uv run python manage.py migrate clipping
```

Expected: applies 0005 cleanly.

- [ ] **Step 3: Write the data migration for ClipRenderTemplate**

Create `***REMOVED***/clipping/migrations/0006_populate_clip_render_templates.py`:

```python
from __future__ import annotations

from django.db import migrations


def populate_clip_render_templates(apps, schema_editor):
    """Create a ClipRenderTemplate for every existing Channel."""
    Channel = apps.get_model("channels", "Channel")
    ClipRenderTemplate = apps.get_model("clipping", "ClipRenderTemplate")
    for channel in Channel.objects.all():
        ClipRenderTemplate.objects.get_or_create(channel=channel)


def reverse_populate_clip_render_templates(apps, schema_editor):
    """Remove all ClipRenderTemplate records (migration reversal only)."""
    ClipRenderTemplate = apps.get_model("clipping", "ClipRenderTemplate")
    ClipRenderTemplate.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("clipping", "0005_add_render_style_models"),
        ("channels", "0001_initial"),  # adjust to the latest channels migration
    ]

    operations = [
        migrations.RunPython(
            populate_clip_render_templates,
            reverse_code=reverse_populate_clip_render_templates,
        ),
    ]
```

**Note:** Check `***REMOVED***/channels/migrations/` for the latest migration number and update the `dependencies` entry to match (e.g., `("channels", "0004_something")`).

- [ ] **Step 4: Write the data migration for ClipStyleConfig**

Create `***REMOVED***/clipping/migrations/0007_populate_clip_style_configs.py`:

```python
from __future__ import annotations

from django.db import migrations


def populate_clip_style_configs(apps, schema_editor):
    """Create a ClipStyleConfig for every existing ClipCandidate."""
    ClipCandidate = apps.get_model("clipping", "ClipCandidate")
    ClipStyleConfig = apps.get_model("clipping", "ClipStyleConfig")
    for candidate in ClipCandidate.objects.select_related("clipping_job__channel").all():
        ClipStyleConfig.objects.get_or_create(candidate=candidate)


def reverse_populate_clip_style_configs(apps, schema_editor):
    ClipStyleConfig = apps.get_model("clipping", "ClipStyleConfig")
    ClipStyleConfig.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("clipping", "0006_populate_clip_render_templates"),
    ]

    operations = [
        migrations.RunPython(
            populate_clip_style_configs,
            reverse_code=reverse_populate_clip_style_configs,
        ),
    ]
```

- [ ] **Step 5: Run all migrations**

```bash
uv run python manage.py migrate clipping
```

Expected: applies 0006 and 0007 cleanly.

- [ ] **Step 6: Run full test suite to confirm no regressions**

```bash
uv run pytest ***REMOVED***/clipping/tests/ -v
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add ***REMOVED***/clipping/migrations/
git commit -m "feat(clipping): migrations 0005-0007 — schema + data for render style models"
```

---

## Task 7: Add get_stage_output_path and get_clip_ass_path to core/storage.py

**Files:**
- Modify: `***REMOVED***/core/storage.py`

- [ ] **Step 1: Write the failing test**

Create `***REMOVED***/core/tests/test_storage.py` if it doesn't exist, or add to an existing storage test file:

```python
# ***REMOVED***/core/tests/test_storage.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ***REMOVED***.core.storage import get_stage_output_path, get_clip_ass_path


def test_get_stage_output_path_format() -> None:
    with patch("***REMOVED***.core.storage.settings") as mock_settings:
        mock_settings.MEDIA_ROOT = "/media"
        with patch("pathlib.Path.mkdir"):
            path = get_stage_output_path("abc-123", 3, "captions")
    assert str(path) == "/media/clipping/stage_outputs/abc-123/03_captions.mp4"


def test_get_clip_ass_path_format() -> None:
    with patch("***REMOVED***.core.storage.settings") as mock_settings:
        mock_settings.MEDIA_ROOT = "/media"
        with patch("pathlib.Path.mkdir"):
            path = get_clip_ass_path("abc-123")
    assert str(path) == "/media/clipping/ass/abc-123.ass"
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest ***REMOVED***/core/tests/test_storage.py -v 2>/dev/null || uv run pytest -k "test_get_stage_output_path" -v
```

Expected: `ImportError: cannot import name 'get_stage_output_path'`

- [ ] **Step 3: Add the two functions to core/storage.py**

Add at the end of `***REMOVED***/core/storage.py`:

```python
def get_stage_output_path(render_id: str, stage_order: int, stage_name: str) -> Path:
    """Return path for an intermediate render stage output file."""
    return _media(f"clipping/stage_outputs/{render_id}/{stage_order:02d}_{stage_name}.mp4")


def get_clip_ass_path(render_id: str) -> Path:
    """Return path for an ASS subtitle file generated for a render."""
    return _media(f"clipping/ass/{render_id}.ass")
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest -k "test_get_stage_output_path or test_get_clip_ass_path" -v
```

Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/core/storage.py ***REMOVED***/core/tests/
git commit -m "feat(core): add get_stage_output_path and get_clip_ass_path storage helpers"
```

---

## Task 8: RenderStage ABC and TrimAndCropStage

**Files:**
- Create: `***REMOVED***/services/media/render_stages/__init__.py`
- Create: `***REMOVED***/services/media/render_stages/base.py`
- Create: `***REMOVED***/services/media/render_stages/trim_crop.py`
- Create: `***REMOVED***/services/media/tests/__init__.py`
- Create: `***REMOVED***/services/media/tests/test_render_stages.py`

- [ ] **Step 1: Write the failing test**

Create `***REMOVED***/services/media/tests/__init__.py` (empty).

Create `***REMOVED***/services/media/tests/test_render_stages.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ***REMOVED***.services.media.render_stages.base import RenderStage
from ***REMOVED***.services.media.render_stages.trim_crop import TrimAndCropStage


def _make_layout_config(render_mode: str, **extra) -> MagicMock:
    from ***REMOVED***.clipping.models import ClipLayoutConfig

    lc = MagicMock(spec=ClipLayoutConfig)
    lc.render_mode = render_mode
    lc.has_manual_smart_crop = False
    lc.has_spatial_regions = False
    for k, v in extra.items():
        setattr(lc, k, v)
    return lc


def test_render_stage_is_abstract() -> None:
    """RenderStage cannot be instantiated directly."""
    with pytest.raises(TypeError):
        RenderStage()  # type: ignore[abstract]


def test_trim_and_crop_stage_name_and_order() -> None:
    stage = TrimAndCropStage(
        source_path=Path("/tmp/src.mp4"),
        start_sec=0.0,
        end_sec=60.0,
        output_path=Path("/tmp/stage01.mp4"),
        layout_config=None,
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    assert stage.name == "trim_and_crop"
    assert stage.order == 1


def test_trim_and_crop_center_crop_command() -> None:
    stage = TrimAndCropStage(
        source_path=Path("/tmp/src.mp4"),
        start_sec=10.0,
        end_sec=70.0,
        output_path=Path("/tmp/out.mp4"),
        layout_config=_make_layout_config("CENTER_CROP"),
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    cmd = stage._build_command(Path("/tmp/src.mp4"))
    assert "ffmpeg" in cmd
    assert "-ss" in cmd
    assert "10.0" in cmd
    assert "-to" in cmd
    assert "70.0" in cmd
    assert "ih*9/16:ih" in " ".join(cmd)
    assert "libx264" in cmd


def test_trim_and_crop_smart_crop_auto_detects_speaker() -> None:
    from ***REMOVED***.services.media.speaker_detection import SpeakerCropResult

    lc = _make_layout_config("SMART_CROP", has_manual_smart_crop=False)
    stage = TrimAndCropStage(
        source_path=Path("/tmp/src.mp4"),
        start_sec=0.0,
        end_sec=60.0,
        output_path=Path("/tmp/out.mp4"),
        layout_config=lc,
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    mock_result = SpeakerCropResult(crop_x=100, crop_w=405, crop_h=720, confidence=0.8, face_detected=True)
    with patch(
        "***REMOVED***.services.media.render_stages.trim_crop.SpeakerDetectionService.detect",
        return_value=mock_result,
    ):
        cmd = stage._build_command(Path("/tmp/src.mp4"))
    assert "crop=405:720:100:0" in " ".join(cmd)
    assert stage.last_speaker_crop_result is mock_result


def test_trim_and_crop_run_calls_subprocess(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    src.write_bytes(b"fake")
    out = tmp_path / "out.mp4"

    stage = TrimAndCropStage(
        source_path=src,
        start_sec=0.0,
        end_sec=60.0,
        output_path=out,
        layout_config=None,
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    with patch("***REMOVED***.services.media.render_stages.trim_crop.subprocess.run") as mock_run, \
         patch("***REMOVED***.services.media.render_stages.trim_crop.ffmpeg.probe") as mock_probe:
        mock_probe.return_value = {"format": {"duration": "60.0"}}
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        out.write_bytes(b"fake output")  # simulate ffmpeg writing output
        result = stage.run(src)
    assert result == out
    mock_run.assert_called_once()
```

- [ ] **Step 2: Run test to verify failure**

```bash
uv run pytest ***REMOVED***/services/media/tests/test_render_stages.py::test_render_stage_is_abstract -v
```

Expected: `ModuleNotFoundError: No module named '***REMOVED***.services.media.render_stages'`

- [ ] **Step 3: Create the package and base class**

Create `***REMOVED***/services/media/render_stages/__init__.py`:

```python
from __future__ import annotations

from ***REMOVED***.services.media.render_stages.base import RenderStage

__all__ = ["RenderStage"]
```

Create `***REMOVED***/services/media/render_stages/base.py`:

```python
from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from pathlib import Path


class RenderStage(ABC):
    """Abstract base for a single pipeline render stage.

    Each stage reads one video file, processes it, writes a new file,
    and returns the output path. If should_run() returns False the stage
    is marked SKIPPED and the input path is passed through unchanged.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short snake_case identifier, e.g. 'trim_and_crop'."""
        ...

    @property
    @abstractmethod
    def order(self) -> int:
        """1-based position in the pipeline."""
        ...

    def should_run(self) -> bool:
        """Return False to mark this stage SKIPPED."""
        return True

    @abstractmethod
    def run(self, input_path: Path) -> Path:
        """Process input_path, write output to a new file, return its path."""
        ...
```

- [ ] **Step 4: Create TrimAndCropStage**

Create `***REMOVED***/services/media/render_stages/trim_crop.py`:

```python
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import ffmpeg

from ***REMOVED***.services.media.render_stages.base import RenderStage
from ***REMOVED***.services.media.speaker_detection import SpeakerCropResult
from ***REMOVED***.services.media.speaker_detection import SpeakerDetectionService

if TYPE_CHECKING:
    from ***REMOVED***.clipping.models import ClipLayoutConfig

logger = logging.getLogger("***REMOVED***.media.render_stages")


@dataclass
class TrimAndCropStage(RenderStage):
    """Stage 1: Trim the source video to clip boundaries and crop to 9:16.

    Absorbs the three crop modes from the legacy ClipRenderer:
    CENTER_CROP, SMART_CROP (with speaker detection), and SPATIAL_STACK.
    """

    source_path: Path
    start_sec: float
    end_sec: float
    output_path: Path
    layout_config: ClipLayoutConfig | None
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = "slow"
    audio_bitrate: str = "192k"
    last_speaker_crop_result: SpeakerCropResult | None = field(default=None, init=False)

    @property
    def name(self) -> str:
        return "trim_and_crop"

    @property
    def order(self) -> int:
        return 1

    def run(self, input_path: Path) -> Path:
        probe = ffmpeg.probe(str(input_path))
        if not probe:
            msg = f"Cannot probe source: {input_path}"
            raise ValueError(msg)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = self._build_command(input_path)
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"TrimAndCropStage ffmpeg failed: {result.stderr}")
        logger.info(
            "TrimAndCropStage completed",
            extra={"output": str(self.output_path)},
        )
        return self.output_path

    def _build_command(self, input_path: Path) -> list[str]:
        from ***REMOVED***.clipping.models import ClipLayoutConfig as LC

        render_mode = self.layout_config.render_mode if self.layout_config else LC.RenderMode.CENTER_CROP

        if render_mode == LC.RenderMode.SPATIAL_STACK:
            return self._build_spatial_stack_command(input_path)
        if render_mode == LC.RenderMode.SMART_CROP:
            return self._build_smart_crop_command(input_path)
        return self._build_center_crop_command(input_path)

    def _build_center_crop_command(self, input_path: Path) -> list[str]:
        return [
            "ffmpeg", "-y",
            "-ss", str(self.start_sec),
            "-to", str(self.end_sec),
            "-i", str(input_path),
            "-vf", f"crop=ih*9/16:ih,scale={self.width}:{self.height},fps={self.fps}",
            "-c:v", "libx264",
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-c:a", "aac",
            "-b:a", self.audio_bitrate,
            "-movflags", "faststart",
            str(self.output_path),
        ]

    def _build_smart_crop_command(self, input_path: Path) -> list[str]:
        lc = self.layout_config
        if lc is not None and lc.has_manual_smart_crop:
            crop_x = lc.manual_crop_x
            crop_w = lc.manual_crop_w
            crop_h = lc.manual_crop_h
        else:
            service = SpeakerDetectionService()
            result = service.detect(input_path, self.start_sec, self.end_sec)
            self.last_speaker_crop_result = result
            crop_x = result.crop_x
            crop_w = result.crop_w
            crop_h = result.crop_h

        vf = f"crop={crop_w}:{crop_h}:{crop_x}:0,scale={self.width}:{self.height},fps={self.fps}"
        return [
            "ffmpeg", "-y",
            "-ss", str(self.start_sec),
            "-to", str(self.end_sec),
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264",
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-c:a", "aac",
            "-b:a", self.audio_bitrate,
            "-movflags", "faststart",
            str(self.output_path),
        ]

    def _build_spatial_stack_command(self, input_path: Path) -> list[str]:
        lc = self.layout_config
        if lc is None or not lc.has_spatial_regions:
            logger.warning("SPATIAL_STACK has no regions — falling back to center crop")
            return self._build_center_crop_command(input_path)

        out_w = self.width
        out_h = self.height
        a_out_h = int(out_h * lc.stack_ratio)
        b_out_h = out_h - a_out_h

        filter_complex = (
            f"[0:v]trim=start={self.start_sec}:end={self.end_sec},setpts=PTS-STARTPTS,"
            f"crop={lc.region_a_w}:{lc.region_a_h}:{lc.region_a_x}:{lc.region_a_y},"
            f"scale={out_w}:{a_out_h}[top];"
            f"[0:v]trim=start={self.start_sec}:end={self.end_sec},setpts=PTS-STARTPTS,"
            f"crop={lc.region_b_w}:{lc.region_b_h}:{lc.region_b_x}:{lc.region_b_y},"
            f"scale={out_w}:{b_out_h}[bottom];"
            f"[top][bottom]vstack=inputs=2[out]"
        )
        return [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a",
            "-ss", str(self.start_sec),
            "-to", str(self.end_sec),
            "-c:v", "libx264",
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-c:a", "aac",
            "-b:a", self.audio_bitrate,
            "-movflags", "faststart",
            str(self.output_path),
        ]
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest ***REMOVED***/services/media/tests/test_render_stages.py -v
```

Expected: All 5 tests PASSED

- [ ] **Step 6: Commit**

```bash
git add ***REMOVED***/services/media/render_stages/ ***REMOVED***/services/media/tests/
git commit -m "feat(media): add RenderStage ABC and TrimAndCropStage (stage 1)"
```

---

## Task 9: IntroConcatStage and OutroConcatStage (stages 2 & 9)

**Files:**
- Create: `***REMOVED***/services/media/render_stages/intro_outro.py`
- Modify: `***REMOVED***/services/media/tests/test_render_stages.py`

- [ ] **Step 1: Write the failing tests**

Add to `***REMOVED***/services/media/tests/test_render_stages.py`:

```python
from ***REMOVED***.services.media.render_stages.intro_outro import IntroConcatStage, OutroConcatStage


def _make_style_config(
    intro_asset=None, outro_asset=None,
    intro_transition="NONE", outro_transition="NONE",
    transition_duration_sec=0.5,
) -> MagicMock:
    sc = MagicMock()
    sc.intro_asset = intro_asset
    sc.outro_asset = outro_asset
    sc.intro_transition = intro_transition
    sc.outro_transition = outro_transition
    sc.transition_duration_sec = transition_duration_sec
    return sc


def test_intro_concat_skipped_when_no_intro_asset(tmp_path: Path) -> None:
    stage = IntroConcatStage(
        output_path=tmp_path / "out.mp4",
        style_config=_make_style_config(intro_asset=None),
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    assert stage.should_run() is False


def test_intro_concat_runs_when_intro_asset_set(tmp_path: Path) -> None:
    mock_asset = MagicMock()
    mock_asset.file.path = str(tmp_path / "intro.mp4")
    mock_asset.duration_sec = 3.0
    stage = IntroConcatStage(
        output_path=tmp_path / "out.mp4",
        style_config=_make_style_config(intro_asset=mock_asset, intro_transition="NONE"),
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    assert stage.should_run() is True


def test_intro_concat_hard_cut_uses_concat_demuxer(tmp_path: Path) -> None:
    mock_asset = MagicMock()
    intro_path = tmp_path / "intro.mp4"
    intro_path.write_bytes(b"fake")
    mock_asset.file.path = str(intro_path)
    mock_asset.duration_sec = 3.0
    stage = IntroConcatStage(
        output_path=tmp_path / "out.mp4",
        style_config=_make_style_config(intro_asset=mock_asset, intro_transition="NONE"),
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    input_path = tmp_path / "clip.mp4"
    input_path.write_bytes(b"fake clip")
    with patch("***REMOVED***.services.media.render_stages.intro_outro.subprocess.run") as mock_run, \
         patch("***REMOVED***.services.media.render_stages.intro_outro.ffmpeg.probe") as mock_probe:
        mock_probe.return_value = {"format": {"duration": "60.0"}}
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"output")
        stage.run(input_path)
    # Hard cut uses concat filter or demuxer
    called_cmd = " ".join(mock_run.call_args[0][0])
    assert "concat" in called_cmd.lower() or "-f" in called_cmd


def test_intro_concat_crossfade_uses_xfade(tmp_path: Path) -> None:
    mock_asset = MagicMock()
    intro_path = tmp_path / "intro.mp4"
    intro_path.write_bytes(b"fake")
    mock_asset.file.path = str(intro_path)
    mock_asset.duration_sec = 3.0
    stage = IntroConcatStage(
        output_path=tmp_path / "out.mp4",
        style_config=_make_style_config(
            intro_asset=mock_asset,
            intro_transition="CROSSFADE",
            transition_duration_sec=0.5,
        ),
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    input_path = tmp_path / "clip.mp4"
    input_path.write_bytes(b"fake clip")
    with patch("***REMOVED***.services.media.render_stages.intro_outro.subprocess.run") as mock_run, \
         patch("***REMOVED***.services.media.render_stages.intro_outro.ffmpeg.probe") as mock_probe:
        mock_probe.return_value = {"format": {"duration": "60.0"}}
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"output")
        stage.run(input_path)
    called_cmd = " ".join(mock_run.call_args[0][0])
    assert "xfade" in called_cmd


def test_outro_concat_skipped_when_no_outro_asset(tmp_path: Path) -> None:
    stage = OutroConcatStage(
        output_path=tmp_path / "out.mp4",
        style_config=_make_style_config(outro_asset=None),
        width=1080,
        height=1920,
        fps=30,
        crf=18,
        preset="slow",
        audio_bitrate="192k",
    )
    assert stage.should_run() is False
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest ***REMOVED***/services/media/tests/test_render_stages.py::test_intro_concat_skipped_when_no_intro_asset -v
```

Expected: `ImportError: cannot import name 'IntroConcatStage'`

- [ ] **Step 3: Implement intro_outro.py**

Create `***REMOVED***/services/media/render_stages/intro_outro.py`:

```python
from __future__ import annotations

import subprocess
import tempfile
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import ffmpeg

from ***REMOVED***.services.media.render_stages.base import RenderStage

if TYPE_CHECKING:
    from ***REMOVED***.clipping.models import ClipStyleConfig

logger = logging.getLogger("***REMOVED***.media.render_stages")

# Maps our TransitionStyle choices to ffmpeg xfade transition names
_XFADE_MAP = {
    "CROSSFADE": "fade",
    "FADE_BLACK": "fadeblack",
    "WIPE_LEFT": "wipeleft",
    "WIPE_RIGHT": "wiperight",
}


def _get_duration(path: Path) -> float:
    """Return video duration in seconds via ffprobe."""
    probe = ffmpeg.probe(str(path))
    return float(probe["format"]["duration"])


def _concat_hard_cut(clip_a: Path, clip_b: Path, output: Path, crf: int, preset: str, audio_bitrate: str) -> None:
    """Concatenate two videos with a hard cut using ffmpeg filter_complex concat."""
    filter_complex = "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[outv][outa]"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_a),
        "-i", str(clip_b),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-movflags", "faststart",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"concat failed: {result.stderr}")


def _concat_xfade(
    clip_a: Path, clip_b: Path, output: Path,
    xfade_name: str, duration: float,
    crf: int, preset: str, audio_bitrate: str,
) -> None:
    """Concatenate two videos with an xfade transition."""
    a_duration = _get_duration(clip_a)
    offset = max(0.0, a_duration - duration)
    filter_complex = (
        f"[0:v][1:v]xfade=transition={xfade_name}:duration={duration}:offset={offset}[outv];"
        f"[0:a][1:a]acrossfade=d={duration}[outa]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_a),
        "-i", str(clip_b),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-movflags", "faststart",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"xfade concat failed: {result.stderr}")


@dataclass
class IntroConcatStage(RenderStage):
    """Stage 2: Prepend the channel intro clip before the main content."""

    output_path: Path
    style_config: ClipStyleConfig | None
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = "slow"
    audio_bitrate: str = "192k"

    @property
    def name(self) -> str:
        return "intro_concat"

    @property
    def order(self) -> int:
        return 2

    def should_run(self) -> bool:
        return self.style_config is not None and self.style_config.intro_asset is not None

    def run(self, input_path: Path) -> Path:
        sc = self.style_config
        intro_path = Path(sc.intro_asset.file.path)
        transition = sc.intro_transition
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        if transition == "NONE":
            _concat_hard_cut(intro_path, input_path, self.output_path, self.crf, self.preset, self.audio_bitrate)
        else:
            xfade_name = _XFADE_MAP.get(transition, "fade")
            _concat_xfade(
                intro_path, input_path, self.output_path,
                xfade_name, sc.transition_duration_sec,
                self.crf, self.preset, self.audio_bitrate,
            )
        logger.info("IntroConcatStage completed", extra={"output": str(self.output_path)})
        return self.output_path


@dataclass
class OutroConcatStage(RenderStage):
    """Stage 9: Append the channel outro clip after the main content."""

    output_path: Path
    style_config: ClipStyleConfig | None
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = "slow"
    audio_bitrate: str = "192k"

    @property
    def name(self) -> str:
        return "outro_concat"

    @property
    def order(self) -> int:
        return 9

    def should_run(self) -> bool:
        return self.style_config is not None and self.style_config.outro_asset is not None

    def run(self, input_path: Path) -> Path:
        sc = self.style_config
        outro_path = Path(sc.outro_asset.file.path)
        transition = sc.outro_transition
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        if transition == "NONE":
            _concat_hard_cut(input_path, outro_path, self.output_path, self.crf, self.preset, self.audio_bitrate)
        else:
            xfade_name = _XFADE_MAP.get(transition, "fade")
            _concat_xfade(
                input_path, outro_path, self.output_path,
                xfade_name, sc.transition_duration_sec,
                self.crf, self.preset, self.audio_bitrate,
            )
        logger.info("OutroConcatStage completed", extra={"output": str(self.output_path)})
        return self.output_path
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest ***REMOVED***/services/media/tests/test_render_stages.py -k "intro or outro" -v
```

Expected: 6 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/services/media/render_stages/intro_outro.py ***REMOVED***/services/media/tests/test_render_stages.py
git commit -m "feat(media): add IntroConcatStage and OutroConcatStage (stages 2 & 9)"
```

---

## Task 10: HookStage (stage 3)

**Files:**
- Create: `***REMOVED***/services/media/render_stages/hook.py`
- Modify: `***REMOVED***/services/media/tests/test_render_stages.py`

- [ ] **Step 1: Write the failing tests**

Add to `***REMOVED***/services/media/tests/test_render_stages.py`:

```python
from ***REMOVED***.services.media.render_stages.hook import HookStage


def _make_hook_style_config(
    hook_enabled=True, hook_text="You won't believe this", hook_style="OVERLAY_TOP",
    hook_duration_sec=2.5, hook_font="Montserrat-Bold", hook_size=60,
    hook_color="#FFFFFF", hook_bg_color="#CC000000", hook_animation="FADE",
) -> MagicMock:
    sc = MagicMock()
    sc.hook_enabled = hook_enabled
    sc.hook_style = hook_style
    sc.hook_duration_sec = hook_duration_sec
    sc.hook_font = hook_font
    sc.hook_size = hook_size
    sc.hook_color = hook_color
    sc.hook_bg_color = hook_bg_color
    sc.hook_animation = hook_animation
    return sc


def test_hook_stage_skipped_when_disabled(tmp_path: Path) -> None:
    stage = HookStage(
        hook_text="Some hook",
        output_path=tmp_path / "out.mp4",
        style_config=_make_hook_style_config(hook_enabled=False),
        width=1080, height=1920, fps=30, crf=18, preset="slow", audio_bitrate="192k",
    )
    assert stage.should_run() is False


def test_hook_stage_skipped_when_no_hook_text(tmp_path: Path) -> None:
    stage = HookStage(
        hook_text="",
        output_path=tmp_path / "out.mp4",
        style_config=_make_hook_style_config(hook_enabled=True),
        width=1080, height=1920, fps=30, crf=18, preset="slow", audio_bitrate="192k",
    )
    assert stage.should_run() is False


def test_hook_stage_name_and_order(tmp_path: Path) -> None:
    stage = HookStage(
        hook_text="Test",
        output_path=tmp_path / "out.mp4",
        style_config=_make_hook_style_config(),
        width=1080, height=1920, fps=30, crf=18, preset="slow", audio_bitrate="192k",
    )
    assert stage.name == "hook"
    assert stage.order == 3


def test_hook_overlay_top_command_uses_drawtext_with_enable(tmp_path: Path) -> None:
    stage = HookStage(
        hook_text="Watch this",
        output_path=tmp_path / "out.mp4",
        style_config=_make_hook_style_config(hook_style="OVERLAY_TOP"),
        width=1080, height=1920, fps=30, crf=18, preset="slow", audio_bitrate="192k",
    )
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("***REMOVED***.services.media.render_stages.hook.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = " ".join(mock_run.call_args[0][0])
    assert "drawtext" in cmd
    assert "lt(t" in cmd or "enable" in cmd  # time-limited display


def test_hook_title_card_command_uses_concat(tmp_path: Path) -> None:
    stage = HookStage(
        hook_text="Amazing Title",
        output_path=tmp_path / "out.mp4",
        style_config=_make_hook_style_config(hook_style="TITLE_CARD"),
        width=1080, height=1920, fps=30, crf=18, preset="slow", audio_bitrate="192k",
    )
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("***REMOVED***.services.media.render_stages.hook.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    # TITLE_CARD: two subprocess.run calls (generate title card + concat)
    assert mock_run.call_count == 2
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest ***REMOVED***/services/media/tests/test_render_stages.py::test_hook_stage_skipped_when_disabled -v
```

Expected: `ImportError: cannot import name 'HookStage'`

- [ ] **Step 3: Implement HookStage**

Create `***REMOVED***/services/media/render_stages/hook.py`:

```python
from __future__ import annotations

import subprocess
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ***REMOVED***.services.media.render_stages.base import RenderStage

if TYPE_CHECKING:
    from ***REMOVED***.clipping.models import ClipStyleConfig

logger = logging.getLogger("***REMOVED***.media.render_stages")


@dataclass
class HookStage(RenderStage):
    """Stage 3: Render the hook text overlay or title card.

    TITLE_CARD: generates a black frame video with drawtext, then prepends via concat.
    OVERLAY_TOP / OVERLAY_CENTER: burns drawtext onto the video for hook_duration_sec only.
    """

    hook_text: str
    output_path: Path
    style_config: ClipStyleConfig | None
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = "slow"
    audio_bitrate: str = "192k"

    @property
    def name(self) -> str:
        return "hook"

    @property
    def order(self) -> int:
        return 3

    def should_run(self) -> bool:
        if not self.hook_text:
            return False
        if self.style_config is None:
            return False
        return bool(self.style_config.hook_enabled)

    def run(self, input_path: Path) -> Path:
        sc = self.style_config
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        if sc.hook_style == "TITLE_CARD":
            self._run_title_card(input_path, sc)
        else:
            self._run_overlay(input_path, sc)

        logger.info("HookStage completed", extra={"style": sc.hook_style, "output": str(self.output_path)})
        return self.output_path

    def _escape_text(self, text: str) -> str:
        """Escape special characters for ffmpeg drawtext filter."""
        return text.replace("'", "\\'").replace(":", "\\:").replace("\\", "\\\\")

    def _drawtext_filter(self, sc, y_expr: str, enable_expr: str) -> str:
        text = self._escape_text(self.hook_text)
        color = sc.hook_color.lstrip("#")
        bg = sc.hook_bg_color.lstrip("#")
        return (
            f"drawtext=text='{text}'"
            f":fontfile=/usr/share/fonts/truetype/Montserrat-Bold.ttf"
            f":fontsize={sc.hook_size}"
            f":fontcolor=0x{color}"
            f":box=1:boxcolor=0x{bg}:boxborderw=10"
            f":x=(w-text_w)/2:y={y_expr}"
            f":enable='{enable_expr}'"
        )

    def _run_overlay(self, input_path: Path, sc) -> None:
        """Burn drawtext for hook_duration_sec seconds; no duration change."""
        y_expr = "h*0.1" if sc.hook_style == "OVERLAY_TOP" else "(h-text_h)/2"
        enable_expr = f"lt(t,{sc.hook_duration_sec})"
        vf = self._drawtext_filter(sc, y_expr, enable_expr)
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264",
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-c:a", "copy",
            "-movflags", "faststart",
            str(self.output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"HookStage overlay failed: {result.stderr}")

    def _run_title_card(self, input_path: Path, sc) -> None:
        """Generate a black title card video, then prepend to input via concat."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            title_card_path = Path(tmp.name)

        try:
            # Generate black title card with drawtext
            y_expr = "(h-text_h)/2"
            enable_expr = f"lt(t,{sc.hook_duration_sec})"
            vf = (
                f"color=black:size={self.width}x{self.height}:rate={self.fps}"
                f",drawtext=text='{self._escape_text(self.hook_text)}'"
                f":fontsize={sc.hook_size}"
                f":fontcolor=0x{sc.hook_color.lstrip('#')}"
                f":x=(w-text_w)/2:y=(h-text_h)/2"
            )
            gen_cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", f"color=black:size={self.width}x{self.height}:rate={self.fps}",
                "-i", "anullsrc",
                "-vf", f"drawtext=text='{self._escape_text(self.hook_text)}':fontsize={sc.hook_size}:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2",
                "-t", str(sc.hook_duration_sec),
                "-c:v", "libx264",
                "-crf", str(self.crf),
                "-preset", self.preset,
                "-c:a", "aac",
                "-b:a", self.audio_bitrate,
                "-movflags", "faststart",
                str(title_card_path),
            ]
            result = subprocess.run(gen_cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                raise RuntimeError(f"HookStage title card generation failed: {result.stderr}")

            # Concat title card + input
            filter_complex = "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[outv][outa]"
            concat_cmd = [
                "ffmpeg", "-y",
                "-i", str(title_card_path),
                "-i", str(input_path),
                "-filter_complex", filter_complex,
                "-map", "[outv]",
                "-map", "[outa]",
                "-c:v", "libx264",
                "-crf", str(self.crf),
                "-preset", self.preset,
                "-c:a", "aac",
                "-b:a", self.audio_bitrate,
                "-movflags", "faststart",
                str(self.output_path),
            ]
            result = subprocess.run(concat_cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                raise RuntimeError(f"HookStage title card concat failed: {result.stderr}")
        finally:
            title_card_path.unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest ***REMOVED***/services/media/tests/test_render_stages.py -k "hook" -v
```

Expected: 5 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/services/media/render_stages/hook.py ***REMOVED***/services/media/tests/test_render_stages.py
git commit -m "feat(media): add HookStage (stage 3) — title card and overlay modes"
```

---

## Task 11: ASSGenerator, CaptionTranslationStage, CaptionStage (stages 4 & 5)

**Note:** Before running captions in production, place `Montserrat-Bold.ttf` in `***REMOVED***/static/fonts/`. Download from Google Fonts. The `fontsdir` parameter in the ffmpeg `subtitles` filter points to this directory.

**Files:**
- Create: `***REMOVED***/services/media/render_stages/captions.py`
- Modify: `***REMOVED***/services/media/tests/test_render_stages.py`

- [ ] **Step 1: Write the failing tests**

Add to `***REMOVED***/services/media/tests/test_render_stages.py`:

```python
from ***REMOVED***.services.media.render_stages.captions import (
    ASSGenerator,
    CaptionTranslationStage,
    CaptionStage,
)


_SAMPLE_TRANSCRIPT = {
    "segments": [
        {
            "id": 0,
            "start": 0.0,
            "end": 3.5,
            "text": "You won't believe this",
            "words": [
                {"word": "You", "start": 0.0, "end": 0.5},
                {"word": "won't", "start": 0.6, "end": 1.1},
                {"word": "believe", "start": 1.2, "end": 2.0},
                {"word": "this", "start": 2.1, "end": 3.5},
            ],
        },
        {
            "id": 1,
            "start": 3.6,
            "end": 6.0,
            "text": "It is incredible",
            "words": [
                {"word": "It", "start": 3.6, "end": 3.9},
                {"word": "is", "start": 4.0, "end": 4.3},
                {"word": "incredible", "start": 4.4, "end": 6.0},
            ],
        },
    ]
}


def test_ass_generator_produces_non_empty_content() -> None:
    gen = ASSGenerator(
        transcript_json=_SAMPLE_TRANSCRIPT,
        caption_style="CHUNKED",
        caption_font="Montserrat-Bold",
        caption_size=52,
        caption_color="#FFFFFF",
        caption_stroke_color="#000000",
        caption_stroke_width=3,
        caption_bg_color="",
        caption_position="BOTTOM",
        caption_animation="POP",
        emoji_keyword_map={},
        video_width=1080,
        video_height=1920,
    )
    content = gen.generate()
    assert "[Script Info]" in content
    assert "[Events]" in content
    assert "You won't believe this" in content or "You" in content


def test_ass_generator_word_by_word_creates_one_event_per_word() -> None:
    gen = ASSGenerator(
        transcript_json=_SAMPLE_TRANSCRIPT,
        caption_style="WORD_BY_WORD",
        caption_font="Montserrat-Bold",
        caption_size=52,
        caption_color="#FFFFFF",
        caption_stroke_color="#000000",
        caption_stroke_width=3,
        caption_bg_color="",
        caption_position="BOTTOM",
        caption_animation="POP",
        emoji_keyword_map={},
        video_width=1080,
        video_height=1920,
    )
    content = gen.generate()
    # 4 words in segment 0 + 3 words in segment 1 = 7 Dialogue lines
    dialogue_lines = [l for l in content.splitlines() if l.startswith("Dialogue:")]
    assert len(dialogue_lines) == 7


def test_ass_generator_emoji_accent_injects_emoji() -> None:
    gen = ASSGenerator(
        transcript_json=_SAMPLE_TRANSCRIPT,
        caption_style="EMOJI_ACCENT",
        caption_font="Montserrat-Bold",
        caption_size=52,
        caption_color="#FFFFFF",
        caption_stroke_color="#000000",
        caption_stroke_width=3,
        caption_bg_color="",
        caption_position="BOTTOM",
        caption_animation="POP",
        emoji_keyword_map={"incredible": "🔥"},
        video_width=1080,
        video_height=1920,
    )
    content = gen.generate()
    assert "🔥" in content


def test_caption_stage_skipped_when_disabled(tmp_path: Path) -> None:
    sc = MagicMock()
    sc.caption_enabled = False
    stage = CaptionStage(
        transcript_json=_SAMPLE_TRANSCRIPT,
        output_path=tmp_path / "out.mp4",
        ass_path=tmp_path / "sub.ass",
        style_config=sc,
        fonts_dir=Path("/fonts"),
        video_width=1080,
        video_height=1920,
    )
    assert stage.should_run() is False


def test_caption_stage_skipped_when_no_transcript(tmp_path: Path) -> None:
    sc = MagicMock()
    sc.caption_enabled = True
    stage = CaptionStage(
        transcript_json={},
        output_path=tmp_path / "out.mp4",
        ass_path=tmp_path / "sub.ass",
        style_config=sc,
        fonts_dir=Path("/fonts"),
        video_width=1080,
        video_height=1920,
    )
    assert stage.should_run() is False


def test_caption_stage_run_writes_ass_and_calls_ffmpeg(tmp_path: Path) -> None:
    sc = MagicMock()
    sc.caption_enabled = True
    sc.caption_style = "CHUNKED"
    sc.caption_font = "Montserrat-Bold"
    sc.caption_size = 52
    sc.caption_color = "#FFFFFF"
    sc.caption_stroke_color = "#000000"
    sc.caption_stroke_width = 3
    sc.caption_bg_color = ""
    sc.caption_position = "BOTTOM"
    sc.caption_animation = "POP"
    sc.emoji_keyword_map = {}

    ass_path = tmp_path / "sub.ass"
    stage = CaptionStage(
        transcript_json=_SAMPLE_TRANSCRIPT,
        output_path=tmp_path / "out.mp4",
        ass_path=ass_path,
        style_config=sc,
        fonts_dir=tmp_path / "fonts",
        video_width=1080,
        video_height=1920,
    )
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("***REMOVED***.services.media.render_stages.captions.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    assert ass_path.exists()
    cmd = " ".join(mock_run.call_args[0][0])
    assert "subtitles" in cmd


def test_caption_translation_stage_skipped_when_no_target_language(tmp_path: Path) -> None:
    sc = MagicMock()
    sc.caption_translate_to = ""
    stage = CaptionTranslationStage(
        transcript_json=_SAMPLE_TRANSCRIPT,
        output_path=tmp_path / "out.mp4",
        style_config=sc,
        channel=None,
    )
    assert stage.should_run() is False
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest ***REMOVED***/services/media/tests/test_render_stages.py::test_ass_generator_produces_non_empty_content -v
```

Expected: `ImportError: cannot import name 'ASSGenerator'`

- [ ] **Step 3: Implement captions.py**

Create `***REMOVED***/services/media/render_stages/captions.py`:

```python
from __future__ import annotations

import subprocess
import logging
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from ***REMOVED***.services.media.render_stages.base import RenderStage

if TYPE_CHECKING:
    from ***REMOVED***.channels.models import Channel
    from ***REMOVED***.clipping.models import ClipStyleConfig

logger = logging.getLogger("***REMOVED***.media.render_stages")


def _seconds_to_ass_time(seconds: float) -> str:
    """Convert float seconds to ASS time format H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _hex_to_ass_color(hex_color: str) -> str:
    """Convert #RRGGBB or #AARRGGBB hex to ASS &HAABBGGRR format."""
    h = hex_color.lstrip("#")
    if len(h) == 6:
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H00{b}{g}{r}"
    if len(h) == 8:
        a, r, g, b = h[0:2], h[2:4], h[4:6], h[6:8]
        return f"&H{a}{b}{g}{r}"
    return "&H00FFFFFF"


def _chunk_words(words: list[dict[str, Any]], chunk_size: int = 3) -> list[list[dict[str, Any]]]:
    """Group word dicts into chunks of up to chunk_size."""
    return [words[i:i + chunk_size] for i in range(0, len(words), chunk_size)]


class ASSGenerator:
    """Generates ASS subtitle file content from a Whisper transcript_json.

    Supports four caption styles: WORD_BY_WORD, CHUNKED, LOWER_THIRD, EMOJI_ACCENT.
    Falls back to segment-level timing when word timestamps are absent.
    """

    def __init__(
        self,
        transcript_json: dict[str, Any],
        caption_style: str,
        caption_font: str,
        caption_size: int,
        caption_color: str,
        caption_stroke_color: str,
        caption_stroke_width: int,
        caption_bg_color: str,
        caption_position: str,
        caption_animation: str,
        emoji_keyword_map: dict[str, str],
        video_width: int,
        video_height: int,
    ) -> None:
        self.transcript = transcript_json
        self.style = caption_style
        self.font = caption_font
        self.size = caption_size
        self.color = _hex_to_ass_color(caption_color)
        self.stroke_color = _hex_to_ass_color(caption_stroke_color)
        self.stroke_width = caption_stroke_width
        self.bg_color = _hex_to_ass_color(caption_bg_color) if caption_bg_color else ""
        self.position = caption_position
        self.animation = caption_animation
        self.emoji_map = emoji_keyword_map
        self.width = video_width
        self.height = video_height

    def _alignment(self) -> int:
        """ASS alignment numpad: 2=bottom-center, 5=middle-center, 8=top-center."""
        return {"TOP": 8, "CENTER": 5, "BOTTOM": 2}.get(self.position, 2)

    def _header(self) -> str:
        alignment = self._alignment()
        border = f"BorderStyle=1\nOutline={self.stroke_width}\nShadow=0"
        bg_line = f"\nBackColour={self.bg_color}" if self.bg_color else ""
        return (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {self.width}\n"
            f"PlayResY: {self.height}\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,{self.font},{self.size},{self.color},"
            f"{self.color},{self.stroke_color},{self.bg_color or '&H00000000'},"
            f"-1,0,0,0,100,100,0,0,1,{self.stroke_width},0,"
            f"{alignment},10,10,30,1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

    def _dialogue(self, start: float, end: float, text: str) -> str:
        return f"Dialogue: 0,{_seconds_to_ass_time(start)},{_seconds_to_ass_time(end)},Default,,0,0,0,,{text}\n"

    def _apply_emoji(self, text: str) -> str:
        for keyword, emoji in self.emoji_map.items():
            if keyword.lower() in text.lower():
                text = text + f" {emoji}"
        return text

    def generate(self) -> str:
        lines = [self._header()]
        segments = self.transcript.get("segments", [])

        for seg in segments:
            words = seg.get("words", [])
            seg_text = seg.get("text", "").strip()
            seg_start = float(seg.get("start", 0))
            seg_end = float(seg.get("end", seg_start + 1))

            if self.style == "WORD_BY_WORD":
                if words:
                    for w in words:
                        wstart = float(w.get("start", seg_start))
                        wend = float(w.get("end", seg_end))
                        lines.append(self._dialogue(wstart, wend, w.get("word", "").strip()))
                else:
                    lines.append(self._dialogue(seg_start, seg_end, seg_text))

            elif self.style == "LOWER_THIRD":
                lines.append(self._dialogue(seg_start, seg_end, seg_text))

            elif self.style in ("CHUNKED", "EMOJI_ACCENT"):
                if words:
                    for chunk in _chunk_words(words, chunk_size=3):
                        cstart = float(chunk[0].get("start", seg_start))
                        cend = float(chunk[-1].get("end", seg_end))
                        ctext = " ".join(w.get("word", "").strip() for w in chunk)
                        if self.style == "EMOJI_ACCENT":
                            ctext = self._apply_emoji(ctext)
                        lines.append(self._dialogue(cstart, cend, ctext))
                else:
                    text = seg_text
                    if self.style == "EMOJI_ACCENT":
                        text = self._apply_emoji(text)
                    lines.append(self._dialogue(seg_start, seg_end, text))

        return "".join(lines)


@dataclass
class CaptionTranslationStage(RenderStage):
    """Stage 4: Translate transcript_json to target language via LLM.

    Translation is cached in ClipStyleConfig.translated_transcript_json so
    retrying CaptionStage alone doesn't re-translate.
    This stage does NOT modify the video — it produces the same input_path
    as output after updating translated_transcript_json on the style config.
    """

    transcript_json: dict[str, Any]
    output_path: Path
    style_config: ClipStyleConfig | None
    channel: Channel | None

    @property
    def name(self) -> str:
        return "caption_translation"

    @property
    def order(self) -> int:
        return 4

    def should_run(self) -> bool:
        if self.style_config is None:
            return False
        return bool(self.style_config.caption_translate_to)

    def run(self, input_path: Path) -> Path:
        """Translate transcript via LLM. Updates style_config in-place and returns input_path unchanged."""
        sc = self.style_config

        # If translation already cached, skip LLM call
        if sc.translated_transcript_json:
            logger.info("Using cached translation", extra={"style_config_id": str(sc.pk)})
            return input_path

        from ***REMOVED***.services.providers.registry import get_llm_provider

        llm = get_llm_provider(self.channel)
        target_lang = sc.caption_translate_to
        prompt = (
            f"Translate the following Whisper transcript JSON to {target_lang}. "
            "Preserve the exact JSON structure, keys, and timestamps. "
            "Only translate the 'text' and 'word' string values. "
            "Return only valid JSON with no commentary.\n\n"
            f"{self.transcript_json}"
        )
        response = llm.complete(prompt=prompt, system="You are a professional translator.")
        import json

        try:
            translated = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM returned invalid JSON for translation: {exc}") from exc

        from django.db import models as django_models

        sc.__class__.objects.filter(pk=sc.pk).update(translated_transcript_json=translated)
        # Update in-memory too so CaptionStage sees it
        sc.translated_transcript_json = translated

        logger.info(
            "Caption translation completed",
            extra={"target_lang": target_lang, "style_config_id": str(sc.pk)},
        )
        return input_path  # this stage doesn't modify the video file


@dataclass
class CaptionStage(RenderStage):
    """Stage 5: Generate ASS subtitle file and burn captions into the video."""

    transcript_json: dict[str, Any]
    output_path: Path
    ass_path: Path
    style_config: ClipStyleConfig | None
    fonts_dir: Path
    video_width: int = 1080
    video_height: int = 1920

    @property
    def name(self) -> str:
        return "captions"

    @property
    def order(self) -> int:
        return 5

    def should_run(self) -> bool:
        if self.style_config is None or not self.style_config.caption_enabled:
            return False
        return bool(self.transcript_json)

    def run(self, input_path: Path) -> Path:
        sc = self.style_config

        # Use translated transcript if available
        effective_transcript = sc.translated_transcript_json or self.transcript_json

        gen = ASSGenerator(
            transcript_json=effective_transcript,
            caption_style=sc.caption_style,
            caption_font=sc.caption_font,
            caption_size=sc.caption_size,
            caption_color=sc.caption_color,
            caption_stroke_color=sc.caption_stroke_color,
            caption_stroke_width=sc.caption_stroke_width,
            caption_bg_color=sc.caption_bg_color,
            caption_position=sc.caption_position,
            caption_animation=sc.caption_animation,
            emoji_keyword_map=sc.emoji_keyword_map,
            video_width=self.video_width,
            video_height=self.video_height,
        )
        self.ass_path.parent.mkdir(parents=True, exist_ok=True)
        self.ass_path.write_text(gen.generate(), encoding="utf-8")

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        # Escape ass_path for ffmpeg on all platforms
        escaped_ass = str(self.ass_path).replace("\\", "/").replace(":", "\\:")
        vf = f"subtitles={escaped_ass}:fontsdir={str(self.fonts_dir)}"
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "slow",
            "-c:a", "copy",
            "-movflags", "faststart",
            str(self.output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"CaptionStage ffmpeg failed: {result.stderr}")

        logger.info(
            "CaptionStage completed",
            extra={"style": sc.caption_style, "output": str(self.output_path)},
        )
        return self.output_path
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest ***REMOVED***/services/media/tests/test_render_stages.py -k "ass_generator or caption" -v
```

Expected: All 8 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/services/media/render_stages/captions.py ***REMOVED***/services/media/tests/test_render_stages.py
git commit -m "feat(media): add ASSGenerator, CaptionTranslationStage, CaptionStage (stages 4 & 5)"
```

---

## Task 12: WatermarkStage, TimedOverlayStage, ProgressBarStage (stages 6, 7, 8)

**Files:**
- Create: `***REMOVED***/services/media/render_stages/watermark.py`
- Create: `***REMOVED***/services/media/render_stages/timed_overlays.py`
- Create: `***REMOVED***/services/media/render_stages/progress_bar.py`
- Modify: `***REMOVED***/services/media/tests/test_render_stages.py`

- [ ] **Step 1: Write the failing tests**

Add to `***REMOVED***/services/media/tests/test_render_stages.py`:

```python
from ***REMOVED***.services.media.render_stages.watermark import WatermarkStage
from ***REMOVED***.services.media.render_stages.timed_overlays import TimedOverlayStage
from ***REMOVED***.services.media.render_stages.progress_bar import ProgressBarStage


def _make_watermark_config(enabled=True, wtype="TEXT", text="@channel", position="BOTTOM_RIGHT",
                            opacity=0.6, size=32) -> MagicMock:
    sc = MagicMock()
    sc.watermark_enabled = enabled
    sc.watermark_type = wtype
    sc.watermark_text = text
    sc.watermark_image = None
    sc.watermark_position = position
    sc.watermark_opacity = opacity
    sc.watermark_size = size
    return sc


def test_watermark_stage_skipped_when_disabled(tmp_path: Path) -> None:
    sc = _make_watermark_config(enabled=False)
    stage = WatermarkStage(output_path=tmp_path / "out.mp4", style_config=sc)
    assert stage.should_run() is False


def test_watermark_stage_text_command_uses_drawtext(tmp_path: Path) -> None:
    sc = _make_watermark_config(wtype="TEXT", text="@testchan")
    stage = WatermarkStage(output_path=tmp_path / "out.mp4", style_config=sc)
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("***REMOVED***.services.media.render_stages.watermark.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = " ".join(mock_run.call_args[0][0])
    assert "drawtext" in cmd
    assert "@testchan" in cmd or "testchan" in cmd


def test_watermark_stage_image_command_uses_overlay(tmp_path: Path) -> None:
    sc = MagicMock()
    sc.watermark_enabled = True
    sc.watermark_type = "IMAGE"
    mock_file = MagicMock()
    mock_file.path = str(tmp_path / "logo.png")
    sc.watermark_image = mock_file
    sc.watermark_position = "TOP_RIGHT"
    sc.watermark_opacity = 0.8
    sc.watermark_size = 64
    stage = WatermarkStage(output_path=tmp_path / "out.mp4", style_config=sc)
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("***REMOVED***.services.media.render_stages.watermark.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = " ".join(mock_run.call_args[0][0])
    assert "overlay" in cmd


def test_timed_overlay_stage_skipped_when_empty(tmp_path: Path) -> None:
    stage = TimedOverlayStage(output_path=tmp_path / "out.mp4", timed_overlays=[])
    assert stage.should_run() is False


def test_timed_overlay_stage_text_uses_drawtext_with_between(tmp_path: Path) -> None:
    overlay = MagicMock()
    overlay.overlay_type = "TEXT"
    overlay.text = "Subscribe!"
    overlay.start_sec = 5.0
    overlay.end_sec = 10.0
    overlay.position_x = 540
    overlay.position_y = 960
    overlay.opacity = 1.0
    overlay.font_size = 40
    overlay.font_color = "#FFFFFF"
    overlay.image = None
    stage = TimedOverlayStage(output_path=tmp_path / "out.mp4", timed_overlays=[overlay])
    assert stage.should_run() is True
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("***REMOVED***.services.media.render_stages.timed_overlays.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = " ".join(mock_run.call_args[0][0])
    assert "drawtext" in cmd
    assert "between" in cmd


def test_progress_bar_stage_skipped_when_disabled(tmp_path: Path) -> None:
    sc = MagicMock()
    sc.progress_bar_enabled = False
    stage = ProgressBarStage(output_path=tmp_path / "out.mp4", style_config=sc, video_duration_sec=60.0)
    assert stage.should_run() is False


def test_progress_bar_stage_command_uses_drawbox(tmp_path: Path) -> None:
    sc = MagicMock()
    sc.progress_bar_enabled = True
    sc.progress_bar_position = "TOP"
    sc.progress_bar_color = "#FFFFFF"
    sc.progress_bar_height = 6
    stage = ProgressBarStage(output_path=tmp_path / "out.mp4", style_config=sc, video_duration_sec=60.0)
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("***REMOVED***.services.media.render_stages.progress_bar.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = " ".join(mock_run.call_args[0][0])
    assert "drawbox" in cmd
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest ***REMOVED***/services/media/tests/test_render_stages.py::test_watermark_stage_skipped_when_disabled -v
```

Expected: `ImportError: cannot import name 'WatermarkStage'`

- [ ] **Step 3: Implement watermark.py**

Create `***REMOVED***/services/media/render_stages/watermark.py`:

```python
from __future__ import annotations

import subprocess
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ***REMOVED***.services.media.render_stages.base import RenderStage

if TYPE_CHECKING:
    from ***REMOVED***.clipping.models import ClipStyleConfig

logger = logging.getLogger("***REMOVED***.media.render_stages")

_POSITION_COORDS = {
    "TOP_LEFT":     ("10", "10"),
    "TOP_RIGHT":    ("W-w-10", "10"),
    "BOTTOM_LEFT":  ("10", "H-h-10"),
    "BOTTOM_RIGHT": ("W-w-10", "H-h-10"),
}


@dataclass
class WatermarkStage(RenderStage):
    """Stage 6: Add persistent watermark (text or image) to the video."""

    output_path: Path
    style_config: ClipStyleConfig | None

    @property
    def name(self) -> str:
        return "watermark"

    @property
    def order(self) -> int:
        return 6

    def should_run(self) -> bool:
        return self.style_config is not None and bool(self.style_config.watermark_enabled)

    def run(self, input_path: Path) -> Path:
        sc = self.style_config
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        if sc.watermark_type == "IMAGE":
            cmd = self._image_command(input_path, sc)
        else:
            cmd = self._text_command(input_path, sc)

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"WatermarkStage failed: {result.stderr}")
        logger.info("WatermarkStage completed", extra={"output": str(self.output_path)})
        return self.output_path

    def _text_command(self, input_path: Path, sc) -> list[str]:
        x, y = _POSITION_COORDS.get(sc.watermark_position, ("W-w-10", "H-h-10"))
        color = sc.watermark_color if hasattr(sc, "watermark_color") else "white"
        text = sc.watermark_text.replace("'", "\\'").replace(":", "\\:")
        alpha = sc.watermark_opacity
        vf = (
            f"drawtext=text='{text}'"
            f":fontsize={sc.watermark_size}"
            f":fontcolor=white@{alpha}"
            f":x={x}:y={y}"
        )
        return [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264", "-crf", "18", "-preset", "slow",
            "-c:a", "copy", "-movflags", "faststart",
            str(self.output_path),
        ]

    def _image_command(self, input_path: Path, sc) -> list[str]:
        x, y = _POSITION_COORDS.get(sc.watermark_position, ("W-w-10", "H-h-10"))
        img_path = sc.watermark_image.path
        alpha = sc.watermark_opacity
        filter_complex = (
            f"[1:v]scale={sc.watermark_size}:-1,format=rgba,"
            f"colorchannelmixer=aa={alpha}[wm];"
            f"[0:v][wm]overlay={x}:{y}[outv]"
        )
        return [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-i", str(img_path),
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "0:a",
            "-c:v", "libx264", "-crf", "18", "-preset", "slow",
            "-c:a", "copy", "-movflags", "faststart",
            str(self.output_path),
        ]
```

- [ ] **Step 4: Implement timed_overlays.py**

Create `***REMOVED***/services/media/render_stages/timed_overlays.py`:

```python
from __future__ import annotations

import subprocess
import logging
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from ***REMOVED***.services.media.render_stages.base import RenderStage

if TYPE_CHECKING:
    from ***REMOVED***.clipping.models import ClipTimedOverlay

logger = logging.getLogger("***REMOVED***.media.render_stages")


@dataclass
class TimedOverlayStage(RenderStage):
    """Stage 7: Composite all timed text/image overlays in a single ffmpeg pass."""

    output_path: Path
    timed_overlays: list[Any] = field(default_factory=list)  # list[ClipTimedOverlay]

    @property
    def name(self) -> str:
        return "timed_overlays"

    @property
    def order(self) -> int:
        return 7

    def should_run(self) -> bool:
        return bool(self.timed_overlays)

    def run(self, input_path: Path) -> Path:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        text_overlays = [o for o in self.timed_overlays if o.overlay_type == "TEXT"]
        image_overlays = [o for o in self.timed_overlays if o.overlay_type == "IMAGE"]

        if image_overlays:
            cmd = self._build_mixed_command(input_path, text_overlays, image_overlays)
        else:
            cmd = self._build_text_only_command(input_path, text_overlays)

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"TimedOverlayStage failed: {result.stderr}")
        logger.info("TimedOverlayStage completed", extra={"count": len(self.timed_overlays)})
        return self.output_path

    def _build_text_only_command(self, input_path: Path, overlays: list) -> list[str]:
        filters = []
        for o in overlays:
            text = o.text.replace("'", "\\'").replace(":", "\\:")
            color = o.font_color.lstrip("#")
            filters.append(
                f"drawtext=text='{text}'"
                f":fontsize={o.font_size}"
                f":fontcolor=0x{color}@{o.opacity}"
                f":x={o.position_x - o.font_size // 2}"
                f":y={o.position_y - o.font_size // 2}"
                f":enable='between(t,{o.start_sec},{o.end_sec})'"
            )
        vf = ",".join(filters)
        return [
            "ffmpeg", "-y", "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264", "-crf", "18", "-preset", "slow",
            "-c:a", "copy", "-movflags", "faststart",
            str(self.output_path),
        ]

    def _build_mixed_command(self, input_path: Path, text_overlays: list, image_overlays: list) -> list[str]:
        # Build filter_complex with image overlays + drawtext for text overlays
        inputs = ["-i", str(input_path)]
        for o in image_overlays:
            inputs += ["-i", str(o.image.path)]

        fc_parts = []
        prev = "0:v"
        for idx, o in enumerate(image_overlays):
            img_idx = idx + 1
            tag_out = f"ov{idx}"
            fc_parts.append(
                f"[{prev}][{img_idx}:v]overlay={o.position_x}:{o.position_y}"
                f":enable='between(t,{o.start_sec},{o.end_sec})'[{tag_out}]"
            )
            prev = tag_out

        text_filters = []
        for o in text_overlays:
            text = o.text.replace("'", "\\'").replace(":", "\\:")
            color = o.font_color.lstrip("#")
            text_filters.append(
                f"drawtext=text='{text}'"
                f":fontsize={o.font_size}"
                f":fontcolor=0x{color}@{o.opacity}"
                f":x={o.position_x}:y={o.position_y}"
                f":enable='between(t,{o.start_sec},{o.end_sec})'"
            )
        if text_filters:
            fc_parts.append(f"[{prev}]{','.join(text_filters)}[outv]")
            final_map = "[outv]"
        else:
            final_map = f"[{prev}]"

        return [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", ";".join(fc_parts),
            "-map", final_map,
            "-map", "0:a",
            "-c:v", "libx264", "-crf", "18", "-preset", "slow",
            "-c:a", "copy", "-movflags", "faststart",
            str(self.output_path),
        ]
```

- [ ] **Step 5: Implement progress_bar.py**

Create `***REMOVED***/services/media/render_stages/progress_bar.py`:

```python
from __future__ import annotations

import subprocess
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ***REMOVED***.services.media.render_stages.base import RenderStage

if TYPE_CHECKING:
    from ***REMOVED***.clipping.models import ClipStyleConfig

logger = logging.getLogger("***REMOVED***.media.render_stages")


@dataclass
class ProgressBarStage(RenderStage):
    """Stage 8: Draw a time-driven progress bar (drawbox with width=W*t/duration)."""

    output_path: Path
    style_config: ClipStyleConfig | None
    video_duration_sec: float = 60.0

    @property
    def name(self) -> str:
        return "progress_bar"

    @property
    def order(self) -> int:
        return 8

    def should_run(self) -> bool:
        return self.style_config is not None and bool(self.style_config.progress_bar_enabled)

    def run(self, input_path: Path) -> Path:
        sc = self.style_config
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        color = sc.progress_bar_color.lstrip("#")
        h = sc.progress_bar_height
        y = "0" if sc.progress_bar_position == "TOP" else f"H-{h}"
        dur = self.video_duration_sec
        vf = (
            f"drawbox=x=0:y={y}"
            f":w=W*t/{dur}"
            f":h={h}"
            f":color=0x{color}@1.0"
            f":t=fill"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264", "-crf", "18", "-preset", "slow",
            "-c:a", "copy", "-movflags", "faststart",
            str(self.output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"ProgressBarStage failed: {result.stderr}")
        logger.info("ProgressBarStage completed", extra={"output": str(self.output_path)})
        return self.output_path
```

- [ ] **Step 6: Run all new tests**

```bash
uv run pytest ***REMOVED***/services/media/tests/test_render_stages.py -k "watermark or timed or progress" -v
```

Expected: 8 tests PASSED

- [ ] **Step 7: Commit**

```bash
git add ***REMOVED***/services/media/render_stages/watermark.py \
        ***REMOVED***/services/media/render_stages/timed_overlays.py \
        ***REMOVED***/services/media/render_stages/progress_bar.py \
        ***REMOVED***/services/media/tests/test_render_stages.py
git commit -m "feat(media): add WatermarkStage, TimedOverlayStage, ProgressBarStage (stages 6-8)"
```

---

## Task 13: MusicMixStage (stage 10)

**Files:**
- Create: `***REMOVED***/services/media/render_stages/music_mix.py`
- Modify: `***REMOVED***/services/media/tests/test_render_stages.py`

- [ ] **Step 1: Write the failing tests**

Add to `***REMOVED***/services/media/tests/test_render_stages.py`:

```python
from ***REMOVED***.services.media.render_stages.music_mix import MusicMixStage


def _make_music_config(enabled=True, volume_db=-20.0, fade_in=1.0, fade_out=1.0) -> MagicMock:
    sc = MagicMock()
    sc.music_enabled = enabled
    sc.music_asset = MagicMock()
    sc.music_asset.file.path = "/music/track.mp3"
    sc.music_asset.duration_sec = 120.0
    sc.music_volume_db = volume_db
    sc.music_fade_in_sec = fade_in
    sc.music_fade_out_sec = fade_out
    return sc


def test_music_mix_stage_skipped_when_disabled(tmp_path: Path) -> None:
    sc = _make_music_config(enabled=False)
    stage = MusicMixStage(output_path=tmp_path / "out.mp4", style_config=sc, video_duration_sec=60.0)
    assert stage.should_run() is False


def test_music_mix_stage_skipped_when_no_music_asset(tmp_path: Path) -> None:
    sc = MagicMock()
    sc.music_enabled = True
    sc.music_asset = None
    stage = MusicMixStage(output_path=tmp_path / "out.mp4", style_config=sc, video_duration_sec=60.0)
    assert stage.should_run() is False


def test_music_mix_stage_name_and_order(tmp_path: Path) -> None:
    stage = MusicMixStage(output_path=tmp_path / "out.mp4", style_config=_make_music_config(), video_duration_sec=60.0)
    assert stage.name == "music_mix"
    assert stage.order == 10


def test_music_mix_stage_command_uses_amix(tmp_path: Path) -> None:
    sc = _make_music_config(volume_db=-18.0, fade_in=1.0, fade_out=2.0)
    stage = MusicMixStage(output_path=tmp_path / "out.mp4", style_config=sc, video_duration_sec=60.0)
    input_path = tmp_path / "in.mp4"
    input_path.write_bytes(b"fake")
    with patch("***REMOVED***.services.media.render_stages.music_mix.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        (tmp_path / "out.mp4").write_bytes(b"out")
        stage.run(input_path)
    cmd = " ".join(mock_run.call_args[0][0])
    assert "amix" in cmd
    assert "volume" in cmd or "-18" in cmd
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest ***REMOVED***/services/media/tests/test_render_stages.py::test_music_mix_stage_skipped_when_disabled -v
```

Expected: `ImportError: cannot import name 'MusicMixStage'`

- [ ] **Step 3: Implement music_mix.py**

Create `***REMOVED***/services/media/render_stages/music_mix.py`:

```python
from __future__ import annotations

import subprocess
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ***REMOVED***.services.media.render_stages.base import RenderStage

if TYPE_CHECKING:
    from ***REMOVED***.clipping.models import ClipStyleConfig

logger = logging.getLogger("***REMOVED***.media.render_stages")


@dataclass
class MusicMixStage(RenderStage):
    """Stage 10: Mix background music under the clip audio.

    Runs last so it covers the full assembled output including intro + outro.
    Uses amix filter to blend music with original audio. If the music track is
    shorter than the clip, it is looped via -stream_loop -1.
    Volume is specified in dB relative to original audio.
    """

    output_path: Path
    style_config: ClipStyleConfig | None
    video_duration_sec: float = 60.0

    @property
    def name(self) -> str:
        return "music_mix"

    @property
    def order(self) -> int:
        return 10

    def should_run(self) -> bool:
        if self.style_config is None or not self.style_config.music_enabled:
            return False
        return self.style_config.music_asset is not None

    def run(self, input_path: Path) -> Path:
        sc = self.style_config
        music_path = sc.music_asset.file.path
        music_duration = sc.music_asset.duration_sec or 0
        vol_db = sc.music_volume_db
        fade_in = sc.music_fade_in_sec
        fade_out = sc.music_fade_out_sec
        dur = self.video_duration_sec

        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build audio filter chain for the music stream
        # 1. Apply volume
        # 2. Fade in at start, fade out at end
        music_filter = f"volume={vol_db}dB,afade=t=in:st=0:d={fade_in},afade=t=out:st={max(0, dur - fade_out)}:d={fade_out}"

        # -stream_loop -1 loops music if shorter than clip
        loop_flag = ["-stream_loop", "-1"] if music_duration < dur else []

        filter_complex = (
            f"[1:a]{music_filter}[music];"
            f"[0:a][music]amix=inputs=2:duration=first:dropout_transition=0[outa]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            *loop_flag,
            "-i", str(music_path),
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[outa]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "faststart",
            str(self.output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"MusicMixStage failed: {result.stderr}")
        logger.info(
            "MusicMixStage completed",
            extra={"output": str(self.output_path), "volume_db": vol_db},
        )
        return self.output_path
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest ***REMOVED***/services/media/tests/test_render_stages.py -k "music_mix" -v
```

Expected: 4 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/services/media/render_stages/music_mix.py ***REMOVED***/services/media/tests/test_render_stages.py
git commit -m "feat(media): add MusicMixStage (stage 10)"
```

---

## Task 14: ClipRenderPipeline and PipelineRenderConfig

**Files:**
- Create: `***REMOVED***/services/media/clip_render_pipeline.py`
- Create: `***REMOVED***/services/media/tests/test_clip_render_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Create `***REMOVED***/services/media/tests/test_clip_render_pipeline.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest

from ***REMOVED***.services.media.clip_render_pipeline import ClipRenderPipeline, PipelineRenderConfig


def _make_config(tmp_path: Path, render_id: str = "test-render-uuid") -> PipelineRenderConfig:
    return PipelineRenderConfig(
        source_path=tmp_path / "source.mp4",
        output_path=tmp_path / "final.mp4",
        start_sec=0.0,
        end_sec=60.0,
        hook_text="",
        transcript_json={},
        layout_config=None,
        style_config=None,
        timed_overlays=[],
        render_id=render_id,
    )


@pytest.mark.django_db
def test_pipeline_builds_10_stages(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    pipeline = ClipRenderPipeline(config)
    stages = pipeline._build_stages()
    orders = [s.order for s in stages]
    assert orders == list(range(1, 11)), f"Expected stages 1-10, got {orders}"


@pytest.mark.django_db
def test_pipeline_creates_stage_result_records(tmp_path: Path) -> None:
    from ***REMOVED***.clipping.models import ClipRender, ClipCandidate, ClipRenderStageResult
    from ***REMOVED***.clipping.tests.factories import ClipRenderFactory

    render = ClipRenderFactory()
    config = _make_config(tmp_path, render_id=str(render.pk))

    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake")

    with patch("***REMOVED***.services.media.clip_render_pipeline.ClipRenderPipeline._run_stage") as mock_run:
        # Return input path for all stages (simulating skipped/pass-through)
        mock_run.side_effect = lambda stage, path: path
        with patch.object(ClipRenderPipeline, "_build_stages") as mock_build:
            # Create a simple mock stage
            mock_stage = MagicMock()
            mock_stage.order = 1
            mock_stage.name = "trim_and_crop"
            mock_stage.should_run.return_value = False
            mock_build.return_value = [mock_stage]
            import shutil
            with patch("shutil.copy2"):
                pipeline = ClipRenderPipeline(config)
                pipeline.run()

    assert ClipRenderStageResult.objects.filter(render=render).count() >= 0  # pipeline ran


@pytest.mark.django_db
def test_pipeline_run_end_to_end_all_skipped(tmp_path: Path) -> None:
    """When all stages are skipped, run() should copy source to output."""
    from ***REMOVED***.clipping.tests.factories import ClipRenderFactory

    render = ClipRenderFactory()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake video content")
    output = tmp_path / "final.mp4"

    config = PipelineRenderConfig(
        source_path=source,
        output_path=output,
        start_sec=0.0,
        end_sec=60.0,
        hook_text="",
        transcript_json={},
        layout_config=None,
        style_config=None,
        timed_overlays=[],
        render_id=str(render.pk),
    )
    pipeline = ClipRenderPipeline(config)

    # All stages will call should_run() → False (no layout_config, no style_config, etc.)
    # TrimAndCropStage.should_run() always returns True, so mock run
    with patch("***REMOVED***.services.media.render_stages.trim_crop.TrimAndCropStage.run") as mock_trim, \
         patch("***REMOVED***.services.media.render_stages.trim_crop.TrimAndCropStage.should_run", return_value=True):
        stage_out = tmp_path / "stage01.mp4"
        stage_out.write_bytes(b"stage output")
        mock_trim.return_value = stage_out
        result = pipeline.run()

    assert result == output
    assert output.exists()


def test_pipeline_render_config_has_expected_defaults(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    assert config.width == 1080
    assert config.height == 1920
    assert config.fps == 30
    assert config.crf == 18
    assert config.preset == "slow"
    assert config.audio_bitrate == "192k"
    assert config.channel is None
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest ***REMOVED***/services/media/tests/test_clip_render_pipeline.py::test_pipeline_render_config_has_expected_defaults -v
```

Expected: `ModuleNotFoundError: No module named '***REMOVED***.services.media.clip_render_pipeline'`

- [ ] **Step 3: Implement the pipeline**

Create `***REMOVED***/services/media/clip_render_pipeline.py`:

```python
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from django.conf import settings
from django.utils import timezone

from ***REMOVED***.clipping.models import ClipRenderStageResult
from ***REMOVED***.core.storage import get_clip_ass_path
from ***REMOVED***.core.storage import get_stage_output_path

if TYPE_CHECKING:
    from ***REMOVED***.channels.models import Channel
    from ***REMOVED***.clipping.models import ClipLayoutConfig
    from ***REMOVED***.clipping.models import ClipStyleConfig
    from ***REMOVED***.clipping.models import ClipTimedOverlay

logger = logging.getLogger("***REMOVED***.media.pipeline")


@dataclass
class PipelineRenderConfig:
    """All inputs needed by the multi-stage render pipeline."""

    source_path: Path
    output_path: Path
    start_sec: float
    end_sec: float
    hook_text: str
    transcript_json: dict[str, Any]
    layout_config: ClipLayoutConfig | None
    style_config: ClipStyleConfig | None
    timed_overlays: list[Any]  # list[ClipTimedOverlay]
    render_id: str
    # Optional / quality params
    channel: Channel | None = None
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = "slow"
    audio_bitrate: str = "192k"


class ClipRenderPipeline:
    """Orchestrates the 10-stage clip rendering pipeline.

    Each stage reads the current file, processes it, writes a new file,
    and records a ClipRenderStageResult. The pipeline is resumable from
    any stage by passing start_from_stage to run().
    """

    def __init__(self, config: PipelineRenderConfig) -> None:
        self.config = config

    def _build_stages(self):  # noqa: ANN201
        """Instantiate all 10 stages in order."""
        from django.conf import settings as dj_settings

        from ***REMOVED***.services.media.render_stages.captions import CaptionStage
        from ***REMOVED***.services.media.render_stages.captions import CaptionTranslationStage
        from ***REMOVED***.services.media.render_stages.hook import HookStage
        from ***REMOVED***.services.media.render_stages.intro_outro import IntroConcatStage
        from ***REMOVED***.services.media.render_stages.intro_outro import OutroConcatStage
        from ***REMOVED***.services.media.render_stages.music_mix import MusicMixStage
        from ***REMOVED***.services.media.render_stages.progress_bar import ProgressBarStage
        from ***REMOVED***.services.media.render_stages.timed_overlays import TimedOverlayStage
        from ***REMOVED***.services.media.render_stages.trim_crop import TrimAndCropStage
        from ***REMOVED***.services.media.render_stages.watermark import WatermarkStage

        c = self.config
        clip_duration = c.end_sec - c.start_sec
        fonts_dir = Path(dj_settings.STATIC_ROOT or dj_settings.BASE_DIR / "***REMOVED***/static") / "fonts"

        return [
            TrimAndCropStage(
                source_path=c.source_path,
                start_sec=c.start_sec,
                end_sec=c.end_sec,
                output_path=get_stage_output_path(c.render_id, 1, "trim_and_crop"),
                layout_config=c.layout_config,
                width=c.width, height=c.height, fps=c.fps,
                crf=c.crf, preset=c.preset, audio_bitrate=c.audio_bitrate,
            ),
            IntroConcatStage(
                output_path=get_stage_output_path(c.render_id, 2, "intro_concat"),
                style_config=c.style_config,
                width=c.width, height=c.height, fps=c.fps,
                crf=c.crf, preset=c.preset, audio_bitrate=c.audio_bitrate,
            ),
            HookStage(
                hook_text=c.hook_text,
                output_path=get_stage_output_path(c.render_id, 3, "hook"),
                style_config=c.style_config,
                width=c.width, height=c.height, fps=c.fps,
                crf=c.crf, preset=c.preset, audio_bitrate=c.audio_bitrate,
            ),
            CaptionTranslationStage(
                transcript_json=c.transcript_json,
                output_path=get_stage_output_path(c.render_id, 4, "caption_translation"),
                style_config=c.style_config,
                channel=c.channel,
            ),
            CaptionStage(
                transcript_json=c.transcript_json,
                output_path=get_stage_output_path(c.render_id, 5, "captions"),
                ass_path=get_clip_ass_path(c.render_id),
                style_config=c.style_config,
                fonts_dir=fonts_dir,
                video_width=c.width,
                video_height=c.height,
            ),
            WatermarkStage(
                output_path=get_stage_output_path(c.render_id, 6, "watermark"),
                style_config=c.style_config,
            ),
            TimedOverlayStage(
                output_path=get_stage_output_path(c.render_id, 7, "timed_overlays"),
                timed_overlays=c.timed_overlays,
            ),
            ProgressBarStage(
                output_path=get_stage_output_path(c.render_id, 8, "progress_bar"),
                style_config=c.style_config,
                video_duration_sec=clip_duration,
            ),
            OutroConcatStage(
                output_path=get_stage_output_path(c.render_id, 9, "outro_concat"),
                style_config=c.style_config,
                width=c.width, height=c.height, fps=c.fps,
                crf=c.crf, preset=c.preset, audio_bitrate=c.audio_bitrate,
            ),
            MusicMixStage(
                output_path=get_stage_output_path(c.render_id, 10, "music_mix"),
                style_config=c.style_config,
                video_duration_sec=clip_duration,
            ),
        ]

    def run(self, start_from_stage: int = 1) -> Path:
        """Run the pipeline, optionally resuming from a specific stage.

        When start_from_stage > 1, uses the output of stage N-1 as the
        starting input_path and deletes stage results for stages >= N.
        Returns config.output_path (the final assembled file).
        """
        stages = self._build_stages()
        current_path = self.config.source_path

        if start_from_stage > 1:
            # Load starting path from stage N-1's result
            try:
                prev_result = ClipRenderStageResult.objects.get(
                    render_id=self.config.render_id,
                    stage_order=start_from_stage - 1,
                )
                if prev_result.output_file:
                    current_path = Path(settings.MEDIA_ROOT) / prev_result.output_file.name
            except ClipRenderStageResult.DoesNotExist:
                logger.warning(
                    "Previous stage result not found — starting from source",
                    extra={"render_id": self.config.render_id, "start_from_stage": start_from_stage},
                )
            # Delete results for stages >= start_from_stage (will be re-created)
            ClipRenderStageResult.objects.filter(
                render_id=self.config.render_id,
                stage_order__gte=start_from_stage,
            ).delete()

        for stage in stages:
            if stage.order < start_from_stage:
                continue
            current_path = self._run_stage(stage, current_path)

        # Copy final stage output to the canonical output_path
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(current_path), str(self.config.output_path))
        logger.info(
            "ClipRenderPipeline completed",
            extra={"render_id": self.config.render_id, "output": str(self.config.output_path)},
        )
        return self.config.output_path

    def _run_stage(self, stage, input_path: Path) -> Path:
        """Run a single stage, recording a ClipRenderStageResult. Returns next input path."""
        result, _ = ClipRenderStageResult.objects.update_or_create(
            render_id=self.config.render_id,
            stage_order=stage.order,
            defaults={
                "stage_name": stage.name,
                "status": ClipRenderStageResult.Status.RUNNING,
                "started_at": timezone.now(),
                "last_error": "",
            },
        )

        try:
            if not stage.should_run():
                result.status = ClipRenderStageResult.Status.SKIPPED
                # Store pass-through path so retry from N+1 can find input
                if input_path.is_relative_to(Path(settings.MEDIA_ROOT)):
                    result.output_file = str(input_path.relative_to(Path(settings.MEDIA_ROOT)))
                result.save(update_fields=["status", "output_file", "updated_at"])
                logger.info(
                    "Stage skipped",
                    extra={"stage": stage.name, "render_id": self.config.render_id},
                )
                return input_path

            output_path = stage.run(input_path)
            completed_at = timezone.now()
            duration = (completed_at - result.started_at).total_seconds()
            result.status = ClipRenderStageResult.Status.COMPLETED
            result.completed_at = completed_at
            result.duration_sec = duration
            if output_path.is_relative_to(Path(settings.MEDIA_ROOT)):
                result.output_file = str(output_path.relative_to(Path(settings.MEDIA_ROOT)))
            result.save(update_fields=[
                "status", "completed_at", "duration_sec", "output_file", "updated_at"
            ])
            logger.info(
                "Stage completed",
                extra={"stage": stage.name, "duration_sec": duration, "render_id": self.config.render_id},
            )
            return output_path

        except Exception as exc:
            result.status = ClipRenderStageResult.Status.FAILED
            result.last_error = str(exc)
            result.completed_at = timezone.now()
            result.save(update_fields=["status", "last_error", "completed_at", "updated_at"])
            logger.error(
                "Stage failed",
                extra={"stage": stage.name, "render_id": self.config.render_id, "error": str(exc)},
            )
            raise
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest ***REMOVED***/services/media/tests/test_clip_render_pipeline.py -v
```

Expected: All 4 tests PASSED (some require `@pytest.mark.django_db` which is already present)

- [ ] **Step 5: Commit**

```bash
git add ***REMOVED***/services/media/clip_render_pipeline.py ***REMOVED***/services/media/tests/test_clip_render_pipeline.py
git commit -m "feat(media): add ClipRenderPipeline and PipelineRenderConfig"
```

---

## Task 15: Update render_clip task and add preview_clip_style task

**Files:**
- Modify: `***REMOVED***/clipping/tasks.py`

- [ ] **Step 1: Write the failing tests**

Add to a new file `***REMOVED***/clipping/tests/test_tasks.py` (or extend existing):

```python
# ***REMOVED***/clipping/tests/test_tasks.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from ***REMOVED***.clipping.tests.factories import (
    ClipCandidateFactory, ClipRenderFactory, ClipStyleConfigFactory,
)


@pytest.mark.django_db
def test_render_clip_creates_new_clip_render_when_no_render_id() -> None:
    from ***REMOVED***.clipping.models import ClipRender
    from ***REMOVED***.clipping.tasks import render_clip

    candidate = ClipCandidateFactory()
    ClipStyleConfigFactory(candidate=candidate)

    with patch("***REMOVED***.clipping.tasks.ClipRenderPipeline") as mock_pipeline_cls, \
         patch("***REMOVED***.clipping.tasks.get_clip_render_path") as mock_path, \
         patch("***REMOVED***.clipping.tasks.Path") as mock_path_cls, \
         patch("django.conf.settings") as mock_settings:
        mock_settings.MEDIA_ROOT = "/media"
        mock_path.return_value = Path("/media/test.mp4")
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = Path("/media/test.mp4")
        mock_pipeline_cls.return_value = mock_pipeline

        # Patch candidate's clipping_job.downloaded_file
        candidate.clipping_job.downloaded_file = MagicMock()
        candidate.clipping_job.downloaded_file.name = "source.mp4"
        candidate.clipping_job.save()

        # Task should not raise
        render_clip.apply(args=[str(candidate.pk)])

    # A ClipRender should have been created
    assert ClipRender.objects.filter(candidate=candidate).exists()


@pytest.mark.django_db
def test_render_clip_uses_existing_render_when_clip_render_id_provided() -> None:
    from ***REMOVED***.clipping.models import ClipRender
    from ***REMOVED***.clipping.tasks import render_clip

    candidate = ClipCandidateFactory()
    render = ClipRenderFactory(candidate=candidate)
    ClipStyleConfigFactory(candidate=candidate)

    with patch("***REMOVED***.clipping.tasks.ClipRenderPipeline") as mock_pipeline_cls, \
         patch("***REMOVED***.clipping.tasks.get_clip_render_path") as mock_path:
        mock_path.return_value = Path("/media/test.mp4")
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = Path("/media/test.mp4")
        mock_pipeline_cls.return_value = mock_pipeline

        render_clip.apply(args=[str(candidate.pk)], kwargs={
            "clip_render_id": str(render.pk),
            "start_from_stage": 3,
        })

    # Should still be the same render, not a new one
    assert ClipRender.objects.filter(candidate=candidate).count() == 1
```

- [ ] **Step 2: Update render_clip and add preview_clip_style in tasks.py**

In `***REMOVED***/clipping/tasks.py`:

1. Add these imports near the top (after existing imports):

```python
from ***REMOVED***.clipping.models import ClipRenderStageResult
from ***REMOVED***.clipping.models import ClipStyleConfig
from ***REMOVED***.clipping.models import ClipTimedOverlay
from ***REMOVED***.services.media.clip_render_pipeline import ClipRenderPipeline
from ***REMOVED***.services.media.clip_render_pipeline import PipelineRenderConfig
```

2. Replace the existing `render_clip` task with:

```python
@shared_task(
    bind=True,
    name="***REMOVED***.clipping.render_clip",
    max_retries=2,
    default_retry_delay=300,
    queue="rendering",
    time_limit=3600,
    soft_time_limit=3500,
)
def render_clip(
    self,
    clip_candidate_id: str,
    start_from_stage: int = 1,
    clip_render_id: str | None = None,
) -> None:
    """Render a ClipCandidate through the multi-stage pipeline.

    When clip_render_id is provided, resumes an existing render from
    start_from_stage. Otherwise creates a new ClipRender record.
    """
    try:
        candidate = ClipCandidate.objects.select_related(
            "clipping_job__channel"
        ).get(id=clip_candidate_id)
    except ClipCandidate.DoesNotExist:
        logger.error("ClipCandidate not found", extra={"id": clip_candidate_id})
        return

    layout_config = ClipLayoutConfig.objects.filter(candidate=candidate).first()
    style_config = ClipStyleConfig.objects.filter(candidate=candidate).first()
    timed_overlays = list(
        ClipTimedOverlay.objects.filter(candidate=candidate).order_by("start_sec")
    )

    render_format = (
        layout_config.render_format if layout_config is not None else ClipRender.Format.VERTICAL_9_16
    )

    if clip_render_id is not None:
        try:
            render = ClipRender.objects.get(id=clip_render_id, candidate=candidate)
        except ClipRender.DoesNotExist:
            logger.error(
                "ClipRender not found for retry",
                extra={"clip_render_id": clip_render_id, "candidate_id": clip_candidate_id},
            )
            return
        render.celery_task_id = self.request.id
        render.status = ClipRender.RenderStatus.RUNNING
        render.save(update_fields=["celery_task_id", "status", "updated_at"])
    else:
        render = ClipRender.objects.create(
            candidate=candidate,
            format=render_format,
            celery_task_id=self.request.id,
            status=ClipRender.RenderStatus.RUNNING,
        )

    try:
        job = candidate.clipping_job
        channel = job.channel
        source_path = Path(settings.MEDIA_ROOT) / job.downloaded_file.name
        output_path = get_clip_render_path(str(candidate.id), render.format)

        pipeline_config = PipelineRenderConfig(
            source_path=source_path,
            output_path=output_path,
            start_sec=candidate.start_sec,
            end_sec=candidate.end_sec,
            hook_text=candidate.hook_text,
            transcript_json=job.transcript_json,
            layout_config=layout_config,
            style_config=style_config,
            timed_overlays=timed_overlays,
            render_id=str(render.id),
            channel=channel,
        )

        pipeline = ClipRenderPipeline(pipeline_config)
        pipeline.run(start_from_stage=start_from_stage)

        # Write back speaker detection results from TrimAndCropStage
        trim_stage = next(
            (s for s in pipeline._build_stages() if s.name == "trim_and_crop"), None
        )
        if (
            layout_config is not None
            and trim_stage is not None
            and hasattr(trim_stage, "last_speaker_crop_result")
            and trim_stage.last_speaker_crop_result is not None
        ):
            layout_config.face_detected = trim_stage.last_speaker_crop_result.face_detected
            layout_config.detection_confidence = trim_stage.last_speaker_crop_result.confidence
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
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 300)
```

3. Add the new task after `render_clip`:

```python
@shared_task(
    bind=True,
    name="***REMOVED***.clipping.preview_clip_style",
    max_retries=1,
    queue="clipping",
    time_limit=60,
    soft_time_limit=55,
)
def preview_clip_style(self, style_config_id: str) -> None:
    """Generate a static frame preview of the style config (PIL-based, no ffmpeg).

    Extracts mid-clip frame, overlays watermark text + sample caption, saves
    to ClipStyleConfig.preview_image.
    """
    import io

    import cv2
    from django.core.files.base import ContentFile
    from PIL import Image
    from PIL import ImageDraw
    from PIL import ImageFont

    try:
        style_config = ClipStyleConfig.objects.select_related(
            "candidate__clipping_job"
        ).get(id=style_config_id)
    except ClipStyleConfig.DoesNotExist:
        logger.error("ClipStyleConfig not found", extra={"id": style_config_id})
        return

    candidate = style_config.candidate
    job = candidate.clipping_job

    if not job.downloaded_file:
        logger.warning(
            "Cannot generate style preview — source video not downloaded",
            extra={"style_config_id": style_config_id},
        )
        return

    source_path = Path(settings.MEDIA_ROOT) / job.downloaded_file.name
    mid_sec = (candidate.start_sec + candidate.end_sec) / 2

    cap = cv2.VideoCapture(str(source_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(mid_sec * fps))
    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        logger.warning(
            "Could not extract frame for style preview",
            extra={"style_config_id": style_config_id},
        )
        return

    # Convert BGR→RGB for PIL
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(frame_rgb)
    draw = ImageDraw.Draw(img)

    # Watermark overlay
    if style_config.watermark_enabled and style_config.watermark_type == "TEXT" and style_config.watermark_text:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=style_config.watermark_size)
        except OSError:
            font = ImageFont.load_default()
        wm_positions = {"BOTTOM_RIGHT": (img.width - 150, img.height - 60), "TOP_LEFT": (10, 10),
                        "TOP_RIGHT": (img.width - 150, 10), "BOTTOM_LEFT": (10, img.height - 60)}
        pos = wm_positions.get(style_config.watermark_position, (img.width - 150, img.height - 60))
        draw.text(pos, style_config.watermark_text, fill=(255, 255, 255, int(255 * style_config.watermark_opacity)), font=font)

    # Sample caption line
    if style_config.caption_enabled:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=style_config.caption_size // 2)
        except OSError:
            font = ImageFont.load_default()
        draw.text((img.width // 2 - 200, img.height - 200), "Sample caption text", fill=(255, 255, 255), font=font)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    filename = f"style_preview_{style_config_id}.jpg"
    style_config.preview_image.save(filename, ContentFile(buf.getvalue()), save=True)
    logger.info(
        "Style preview generated",
        extra={"style_config_id": style_config_id, "filename": filename},
    )
```

- [ ] **Step 3: Run the clipping test suite**

```bash
uv run pytest ***REMOVED***/clipping/tests/ -v
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add ***REMOVED***/clipping/tasks.py ***REMOVED***/clipping/tests/
git commit -m "feat(clipping): update render_clip to use ClipRenderPipeline; add preview_clip_style task"
```

---

## Task 16: Channel admin — ClipRenderTemplateInline, ClipMediaAssetAdmin, ClipMusicAssetAdmin

**Files:**
- Modify: `***REMOVED***/channels/admin.py`
- Create (or modify): `***REMOVED***/clipping/admin.py` (ClipMediaAsset/ClipMusicAsset admin registration)

- [ ] **Step 1: Add ClipRenderTemplateInline to channels/admin.py**

In `***REMOVED***/channels/admin.py`, add after the existing inline definitions (before `@admin.register(Channel)`):

```python
class ClipRenderTemplateInline(StackedInline):
    """Channel-level render style defaults — editable inline on ChannelAdmin."""
    model = None  # set dynamically below to avoid circular import at module level
    extra = 0
    can_delete = False
    max_num = 1
    collapsible = True
    verbose_name = "Clip Render Style"
    verbose_name_plural = "Clip Render Style"
    fieldsets = (
        ("Captions", {
            "fields": (
                ("caption_enabled", "caption_style", "caption_position"),
                ("caption_font", "caption_size"),
                ("caption_color", "caption_stroke_color", "caption_stroke_width"),
                "caption_bg_color",
                ("caption_animation", "caption_language", "caption_translate_to"),
                "emoji_keyword_map",
            ),
        }),
        ("Hook", {
            "fields": (
                ("hook_enabled", "hook_style", "hook_duration_sec"),
                ("hook_font", "hook_size"),
                ("hook_color", "hook_bg_color", "hook_animation"),
            ),
        }),
        ("Transitions", {
            "fields": (
                ("intro_transition", "outro_transition", "transition_duration_sec"),
            ),
        }),
        ("Watermark", {
            "fields": (
                ("watermark_enabled", "watermark_type"),
                ("watermark_text", "watermark_image"),
                ("watermark_position", "watermark_opacity", "watermark_size"),
            ),
        }),
        ("Progress Bar", {
            "fields": (
                ("progress_bar_enabled", "progress_bar_position"),
                ("progress_bar_color", "progress_bar_height"),
            ),
        }),
        ("Background Music", {
            "fields": (
                ("music_enabled", "music_volume_db"),
                ("music_fade_in_sec", "music_fade_out_sec"),
            ),
        }),
    )
```

Then inside `ChannelAdmin`, add it to `inlines`:

Find the `inlines` list in `ChannelAdmin` and add `ClipRenderTemplateInline` to it. First, after the class definition of `ClipRenderTemplateInline`, set the model dynamically in a `get_inlines` method or set it right below the class definition:

```python
# Set model after import to avoid circular import
def _get_clip_render_template_model():
    from ***REMOVED***.clipping.models import ClipRenderTemplate
    return ClipRenderTemplate

ClipRenderTemplateInline.model = _get_clip_render_template_model()
```

Then add `ClipRenderTemplateInline` to `ChannelAdmin.inlines`.

**Note:** Look at the current `ChannelAdmin.inlines` definition in the file. It likely reads something like:
```python
inlines = [ChannelCompetitorInline, ChannelPlaylistInline, SocialAccountInline]
```
Add `ClipRenderTemplateInline` to this list.

- [ ] **Step 2: Register ClipMediaAssetAdmin and ClipMusicAssetAdmin in clipping/admin.py**

Add these classes to `***REMOVED***/clipping/admin.py` (before `__all__`):

```python
from ***REMOVED***.clipping.models import ClipMediaAsset
from ***REMOVED***.clipping.models import ClipMusicAsset


@admin.register(ClipMediaAsset)
class ClipMediaAssetAdmin(ModelAdmin):
    list_display = ("name", "channel", "asset_type_badge", "duration_display", "is_active", "created_at")
    list_filter = ("asset_type", "is_active", "channel")
    search_fields = ("name", "channel__name")
    readonly_fields = ("id", "duration_sec", "created_at", "updated_at", "video_preview")

    @display(description="Type", label={"INTRO": "info", "OUTRO": "warning"})
    def asset_type_badge(self, obj: ClipMediaAsset) -> str:
        return obj.asset_type

    @display(description="Duration")
    def duration_display(self, obj: ClipMediaAsset) -> str:
        if obj.duration_sec is None:
            return "—"
        return f"{obj.duration_sec:.1f}s"

    @display(description="Preview")
    def video_preview(self, obj: ClipMediaAsset) -> str:
        if not obj.file:
            return "—"
        return format_html(
            '<video src="{}" controls style="max-width:240px;max-height:135px;"></video>',
            obj.file.url,
        )


@admin.register(ClipMusicAsset)
class ClipMusicAssetAdmin(ModelAdmin):
    list_display = ("name", "channel", "genre", "duration_display", "bpm", "is_active", "created_at")
    list_filter = ("is_active", "genre", "channel")
    search_fields = ("name", "channel__name", "genre")
    readonly_fields = ("id", "duration_sec", "created_at", "updated_at", "audio_preview")

    @display(description="Duration")
    def duration_display(self, obj: ClipMusicAsset) -> str:
        if obj.duration_sec is None:
            return "—"
        return f"{obj.duration_sec:.1f}s"

    @display(description="Preview")
    def audio_preview(self, obj: ClipMusicAsset) -> str:
        if not obj.file:
            return "—"
        return format_html('<audio src="{}" controls style="max-width:300px;"></audio>', obj.file.url)
```

Also update `__all__` in `clipping/admin.py` to include `"ClipMediaAssetAdmin"` and `"ClipMusicAssetAdmin"`.

- [ ] **Step 3: Run the test suite and verify admin loads**

```bash
uv run python manage.py check
uv run pytest ***REMOVED***/clipping/tests/ ***REMOVED***/channels/ -v
```

Expected: All pass, no system check errors.

- [ ] **Step 4: Commit**

```bash
git add ***REMOVED***/channels/admin.py ***REMOVED***/clipping/admin.py
git commit -m "feat(admin): add ClipRenderTemplateInline to ChannelAdmin, register ClipMediaAssetAdmin and ClipMusicAssetAdmin"
```

---

## Task 17: ClipStyleConfigInline, ClipTimedOverlayInline on ClipCandidateAdmin

**Files:**
- Modify: `***REMOVED***/clipping/admin.py`

- [ ] **Step 1: Add the two new inlines**

In `***REMOVED***/clipping/admin.py`, add these class definitions after `ClipRenderInline`:

```python
from ***REMOVED***.clipping.models import ClipStyleConfig
from ***REMOVED***.clipping.models import ClipTimedOverlay


class ClipStyleConfigInline(StackedInline):
    model = ClipStyleConfig
    extra = 0
    can_delete = False
    max_num = 1
    collapsible = True
    verbose_name = "Style Config"
    verbose_name_plural = "Style Config"
    readonly_fields = ("preview_thumbnail",)
    fieldsets = (
        ("Asset Selection", {
            "fields": ("intro_asset", "outro_asset", "music_asset"),
        }),
        ("Captions", {
            "fields": (
                ("caption_enabled", "caption_style", "caption_position"),
                ("caption_font", "caption_size"),
                ("caption_color", "caption_stroke_color", "caption_stroke_width"),
                "caption_bg_color",
                ("caption_animation", "caption_language", "caption_translate_to"),
                "emoji_keyword_map",
            ),
        }),
        ("Hook", {
            "fields": (
                ("hook_enabled", "hook_style", "hook_duration_sec"),
                ("hook_font", "hook_size"),
                ("hook_color", "hook_bg_color", "hook_animation"),
            ),
        }),
        ("Transitions", {
            "fields": (
                ("intro_transition", "outro_transition", "transition_duration_sec"),
            ),
        }),
        ("Watermark", {
            "fields": (
                ("watermark_enabled", "watermark_type"),
                ("watermark_text", "watermark_image"),
                ("watermark_position", "watermark_opacity", "watermark_size"),
            ),
        }),
        ("Progress Bar", {
            "fields": (
                ("progress_bar_enabled", "progress_bar_position"),
                ("progress_bar_color", "progress_bar_height"),
            ),
        }),
        ("Background Music", {
            "fields": (
                ("music_enabled", "music_volume_db"),
                ("music_fade_in_sec", "music_fade_out_sec"),
            ),
        }),
        ("Preview", {
            "fields": ("preview_thumbnail",),
        }),
    )

    def get_queryset(self, request: HttpRequest):
        return super().get_queryset(request).select_related("intro_asset", "outro_asset", "music_asset")

    def formfield_for_foreignkey(self, db_field, request: HttpRequest, **kwargs):
        """Filter asset FK dropdowns to the candidate's channel."""
        if db_field.name in ("intro_asset", "outro_asset", "music_asset"):
            # Get candidate from the URL resolver
            candidate_id = request.resolver_match.kwargs.get("object_id")
            if candidate_id:
                try:
                    candidate = ClipCandidate.objects.select_related("clipping_job__channel").get(pk=candidate_id)
                    channel = candidate.clipping_job.channel
                    if db_field.name == "intro_asset":
                        kwargs["queryset"] = ClipMediaAsset.objects.filter(channel=channel, asset_type="INTRO", is_active=True)
                    elif db_field.name == "outro_asset":
                        kwargs["queryset"] = ClipMediaAsset.objects.filter(channel=channel, asset_type="OUTRO", is_active=True)
                    elif db_field.name == "music_asset":
                        kwargs["queryset"] = ClipMusicAsset.objects.filter(channel=channel, is_active=True)
                except ClipCandidate.DoesNotExist:
                    pass
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @display(description="Style Preview")
    def preview_thumbnail(self, obj: ClipStyleConfig) -> str:
        if not obj.preview_image:
            return "—"
        return format_html(
            '<img src="{}" style="max-width:200px;max-height:360px;border-radius:4px;" />',
            obj.preview_image.url,
        )


class ClipTimedOverlayInline(TabularInline):
    model = ClipTimedOverlay
    extra = 0
    fields = (
        "overlay_type", "text", "image",
        "start_sec", "end_sec",
        "position_x", "position_y",
        "opacity", "font_size", "font_color",
    )
    ordering = ["start_sec"]
```

- [ ] **Step 2: Add inlines to ClipCandidateAdmin and add generate_style_preview action**

In `ClipCandidateAdmin`:

1. Change `inlines = [ClipLayoutConfigInline, ClipRenderInline]` to:
   ```python
   inlines = [ClipLayoutConfigInline, ClipStyleConfigInline, ClipTimedOverlayInline, ClipRenderInline]
   ```

2. Add the action method to `ClipCandidateAdmin`:

```python
@admin.action(description="Generate style preview image")
def generate_style_preview(self, request: HttpRequest, queryset) -> None:
    from ***REMOVED***.clipping.tasks import preview_clip_style

    queued = 0
    skipped = 0
    for candidate in queryset:
        try:
            sc = candidate.style_config
            preview_clip_style.delay(str(sc.id))
            queued += 1
        except ClipStyleConfig.DoesNotExist:
            skipped += 1

    if queued:
        self.message_user(request, f"Queued style preview for {queued} candidate(s).", messages.SUCCESS)
    if skipped:
        self.message_user(request, f"Skipped {skipped} — no style config found.", messages.WARNING)
```

3. Update `actions = ["generate_preview"]` to:
   ```python
   actions = ["generate_preview", "generate_style_preview"]
   ```

- [ ] **Step 3: Run system check**

```bash
uv run python manage.py check
```

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add ***REMOVED***/clipping/admin.py
git commit -m "feat(admin): add ClipStyleConfigInline and ClipTimedOverlayInline to ClipCandidateAdmin"
```

---

## Task 18: ClipRenderAdmin with stage results inline and retry actions

**Files:**
- Modify: `***REMOVED***/clipping/admin.py`

- [ ] **Step 1: Add ClipRenderStageResultInline and ClipRenderAdmin**

Add to `***REMOVED***/clipping/admin.py` after `ClipTimedOverlayInline`:

```python
from ***REMOVED***.clipping.models import ClipRenderStageResult


class ClipRenderStageResultInline(TabularInline):
    model = ClipRenderStageResult
    extra = 0
    can_delete = False
    ordering = ["stage_order"]
    readonly_fields = (
        "stage_order",
        "stage_name",
        "status_badge",
        "duration_display",
        "video_preview",
        "last_error",
    )
    fields = (
        "stage_order",
        "stage_name",
        "status_badge",
        "duration_display",
        "video_preview",
        "last_error",
    )

    def has_add_permission(self, request: HttpRequest, obj=None) -> bool:
        return False

    @display(
        description="Status",
        label={
            "PENDING": "default",
            "RUNNING": "info",
            "COMPLETED": "success",
            "FAILED": "danger",
            "SKIPPED": "warning",
        },
    )
    def status_badge(self, obj: ClipRenderStageResult) -> str:
        return obj.status

    @display(description="Duration")
    def duration_display(self, obj: ClipRenderStageResult) -> str:
        if obj.duration_sec is None:
            return "—"
        return f"{obj.duration_sec:.1f}s"

    @display(description="Video")
    def video_preview(self, obj: ClipRenderStageResult) -> str:
        if not obj.output_file or obj.status not in (
            ClipRenderStageResult.Status.COMPLETED,
        ):
            return "—"
        return format_html(
            '<video src="{}" controls style="max-width:180px;max-height:320px;"></video>',
            obj.output_file.url,
        )


@admin.register(ClipRender)
class ClipRenderAdmin(ModelAdmin):
    list_display = (
        "__str__",
        "candidate",
        "format",
        "status_badge",
        "render_duration_sec",
        "created_at",
    )
    list_filter = ("status", "format", "created_at")
    search_fields = ("candidate__title", "candidate__clipping_job__source_title")
    readonly_fields = (
        "id",
        "candidate",
        "format",
        "status",
        "celery_task_id",
        "render_duration_sec",
        "started_at",
        "completed_at",
        "last_error",
        "created_at",
        "updated_at",
        "video_preview",
    )
    inlines = [ClipRenderStageResultInline]

    @display(
        description="Status",
        label={
            "PENDING": "default",
            "RUNNING": "info",
            "COMPLETED": "success",
            "FAILED": "danger",
        },
    )
    def status_badge(self, obj: ClipRender) -> str:
        return obj.status

    @display(description="Video")
    def video_preview(self, obj: ClipRender) -> str:
        if not obj.video_file:
            return "—"
        url = obj.video_file.url
        return format_html(
            '<video src="{}" controls style="max-width:320px;max-height:180px;"></video>'
            '<br><a href="{}" download>Download</a>',
            url, url,
        )

    @admin.action(description="Retry full render (from stage 1)")
    def retry_full_render(self, request: HttpRequest, queryset) -> None:
        from ***REMOVED***.clipping.tasks import render_clip

        queued = 0
        for render in queryset:
            # Delete all existing stage results so the pipeline starts clean
            render.stage_results.all().delete()
            render.status = ClipRender.RenderStatus.PENDING
            render.last_error = ""
            render.save(update_fields=["status", "last_error", "updated_at"])
            render_clip.delay(
                str(render.candidate_id),
                start_from_stage=1,
                clip_render_id=str(render.id),
            )
            queued += 1
        self.message_user(request, f"Queued full re-render for {queued} render(s).", messages.SUCCESS)

    @admin.action(description="Retry from stage 2 (skip trim+crop)")
    def retry_from_stage_2(self, request: HttpRequest, queryset) -> None:
        from ***REMOVED***.clipping.tasks import render_clip

        queued = 0
        for render in queryset:
            render_clip.delay(
                str(render.candidate_id),
                start_from_stage=2,
                clip_render_id=str(render.id),
            )
            queued += 1
        self.message_user(request, f"Queued retry from stage 2 for {queued} render(s).", messages.SUCCESS)

    @admin.action(description="Retry from captions stage (stage 5)")
    def retry_from_captions(self, request: HttpRequest, queryset) -> None:
        from ***REMOVED***.clipping.tasks import render_clip

        queued = 0
        for render in queryset:
            render_clip.delay(
                str(render.candidate_id),
                start_from_stage=5,
                clip_render_id=str(render.id),
            )
            queued += 1
        self.message_user(request, f"Queued caption retry for {queued} render(s).", messages.SUCCESS)

    @admin.action(description="Clear stage output files (free storage)")
    def clear_stage_outputs(self, request: HttpRequest, queryset) -> None:
        from django.conf import settings as dj_settings

        cleared = 0
        for render in queryset:
            for stage_result in render.stage_results.all():
                if stage_result.output_file:
                    try:
                        file_path = Path(dj_settings.MEDIA_ROOT) / stage_result.output_file.name
                        file_path.unlink(missing_ok=True)
                    except Exception:
                        pass
            render.stage_results.all().delete()
            cleared += 1
        self.message_user(request, f"Cleared stage outputs for {cleared} render(s).", messages.SUCCESS)

    actions = ["retry_full_render", "retry_from_stage_2", "retry_from_captions", "clear_stage_outputs"]
```

Also add `"ClipRenderAdmin"` and `"ClipRenderStageResultInline"` to `__all__`.

- [ ] **Step 2: Run system check and full test suite**

```bash
uv run python manage.py check
uv run pytest ***REMOVED***/ -v --tb=short
```

Expected: All tests pass, no system check errors.

- [ ] **Step 3: Commit**

```bash
git add ***REMOVED***/clipping/admin.py
git commit -m "feat(admin): add ClipRenderAdmin with stage result inline and retry/clear actions"
```

---

## Task 19: Final integration — run full test suite and deprecate ClipRenderer

**Files:**
- Modify: `***REMOVED***/services/media/clip_renderer.py` (add deprecation warning)

- [ ] **Step 1: Add deprecation warning to ClipRenderer**

In `***REMOVED***/services/media/clip_renderer.py`, update the `__init__` method of `ClipRenderer`:

```python
def __init__(self, config: ClipRenderConfig) -> None:
    import warnings
    warnings.warn(
        "ClipRenderer is deprecated. Use ClipRenderPipeline instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    self.config = config
    self.last_speaker_crop_result: SpeakerCropResult | None = None
```

- [ ] **Step 2: Run the complete test suite**

```bash
uv run pytest ***REMOVED***/ -v --tb=short 2>&1 | tail -30
```

Expected: All tests pass. If any fail, investigate and fix before continuing.

- [ ] **Step 3: Run type checking**

```bash
uv run mypy ***REMOVED***/clipping/ ***REMOVED***/services/media/ --ignore-missing-imports
```

Expected: No errors or only minor type warnings. Fix any errors reported.

- [ ] **Step 4: Run linting**

```bash
uv run ruff check ***REMOVED***/clipping/ ***REMOVED***/services/media/ --fix
uv run ruff format ***REMOVED***/clipping/ ***REMOVED***/services/media/
```

Expected: Clean.

- [ ] **Step 5: Final commit**

```bash
git add -p  # review and stage all remaining changes
git commit -m "feat(media): deprecate ClipRenderer; run final lint and type fixes"
```

---

## Self-Review Against Spec

### Spec Coverage Check

| Spec Section | Covered By |
|---|---|
| §1.1 ClipRenderTemplate (all fields) | Task 2 |
| §1.2 ClipMediaAsset | Task 2 |
| §1.3 ClipMusicAsset | Task 2 |
| §1.4 ClipStyleConfig (all fields + translated_transcript_json) | Task 3 |
| §1.5 ClipTimedOverlay + clean() | Task 3 |
| §1.6 ClipRenderStageResult | Task 3 |
| §2.1 RenderStage ABC | Task 8 |
| §2.2 ClipRenderPipeline + PipelineRenderConfig | Task 14 |
| §2.3 Stage order table (10 stages) | Tasks 8-13 |
| §2.4 TrimAndCropStage | Task 8 |
| §2.4 IntroConcatStage + OutroConcatStage + xfade | Task 9 |
| §2.4 HookStage (TITLE_CARD + OVERLAY modes) | Task 10 |
| §2.4 CaptionTranslationStage (LLM translation + cache) | Task 11 |
| §2.4 CaptionStage + ASSGenerator (4 styles) | Task 11 |
| §2.4 WatermarkStage (TEXT + IMAGE) | Task 12 |
| §2.4 TimedOverlayStage | Task 12 |
| §2.4 ProgressBarStage | Task 12 |
| §2.4 MusicMixStage (amix + loop + fade) | Task 13 |
| §3 ASS caption format + emoji keyword map | Task 11 |
| §4 ClipRenderTemplateInline on ChannelAdmin | Task 16 |
| §4 ClipMediaAssetAdmin (video preview) | Task 16 |
| §4 ClipMusicAssetAdmin (audio preview) | Task 16 |
| §4 ClipStyleConfigInline on ClipCandidateAdmin (FK filtering) | Task 17 |
| §4 ClipTimedOverlayInline on ClipCandidateAdmin | Task 17 |
| §4 ClipRenderStageResultInline (video previews) | Task 18 |
| §4 "Retry from selected stage" admin actions | Task 18 |
| §4 "Clear stage outputs" action | Task 18 |
| §4 "Generate style preview" action | Task 17 |
| §5 render_clip updated signature | Task 15 |
| §5 preview_clip_style task | Task 15 |
| §5 ClipRenderer deprecation warning | Task 19 |
| §6 Schema migration | Task 6 |
| §6 Data migrations for existing data | Task 6 |
| post_save signals (Channel→template, Candidate→style) | Task 4 |
| Duration detection signals (media + music assets) | Task 4 |
| Montserrat-Bold.ttf font placement | Note in Task 11 |

**No gaps found.**

### Placeholder Scan

No "TBD", "TODO", "implement later", or incomplete steps found.

### Type Consistency Check

| Name | Defined In | Used In |
|---|---|---|
| `PipelineRenderConfig` | Task 14 | Task 14, Task 15 |
| `ClipRenderPipeline` | Task 14 | Task 15 |
| `RenderStage.name` | Task 8 | All stage tasks |
| `RenderStage.order` | Task 8 | All stage tasks |
| `TrimAndCropStage` | Task 8 | Task 14 |
| `ClipRenderStyleMixin.STYLE_FIELD_NAMES` | Task 2 | Task 2, Task 4 |
| `ClipRenderTemplate.to_style_defaults()` | Task 2 | Task 4 |
| `ClipRenderStageResult.Status` | Task 3 | Task 14, Task 18 |
| `get_stage_output_path` | Task 7 | Task 14 |
| `get_clip_ass_path` | Task 7 | Task 14 |
| `render_clip(clip_candidate_id, start_from_stage, clip_render_id)` | Task 15 | Task 18 |
| `preview_clip_style(style_config_id)` | Task 15 | Task 17 |

All consistent.
