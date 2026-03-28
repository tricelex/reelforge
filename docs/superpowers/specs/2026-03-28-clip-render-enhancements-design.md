# Clip Render Enhancements — Design Spec

**Date:** 2026-03-28
**Status:** Approved
**Scope:** Captions, hook overlays, intro/outro library, watermarks, timed overlays, progress bar

---

## Overview

Enhance the clipping pipeline to support CapCut-level per-clip personalisation: styled captions, hook text overlays, channel intro/outro library, persistent watermarks, time-ranged overlays, and a progress bar. All features support **channel-level defaults** with **per-clip overrides**.

The renderer is refactored from a single FFmpeg command builder into a **multi-stage pipeline** where each concern is an isolated, independently testable `RenderStage`.

---

## 1. Data Models

### 1.1 `ClipRenderTemplate` (channel level defaults)

`OneToOne` with `Channel`. Auto-created when a `Channel` is saved (via `post_save` signal, same pattern as `ClipLayoutConfig`).

**Caption fields:**
- `caption_enabled: BooleanField(default=True)`
- `caption_style: CharField(choices=[WORD_BY_WORD, CHUNKED, LOWER_THIRD, EMOJI_ACCENT], default=CHUNKED)`
- `caption_font: CharField(max_length=100, default="Montserrat-Bold")`
- `caption_size: PositiveIntegerField(default=52)`
- `caption_color: CharField(max_length=9, default="#FFFFFF")` — hex with optional alpha
- `caption_stroke_color: CharField(max_length=9, default="#000000")`
- `caption_stroke_width: PositiveIntegerField(default=3)`
- `caption_bg_color: CharField(max_length=9, blank=True)` — empty = no background box
- `caption_position: CharField(choices=[TOP, CENTER, BOTTOM], default=BOTTOM)`
- `caption_animation: CharField(choices=[POP, FADE, NONE], default=POP)`

**Hook fields:**
- `hook_enabled: BooleanField(default=True)`
- `hook_style: CharField(choices=[TITLE_CARD, OVERLAY_TOP, OVERLAY_CENTER], default=OVERLAY_TOP)`
- `hook_duration_sec: FloatField(default=2.5)` — how long the hook text displays
- `hook_font: CharField(max_length=100, default="Montserrat-Bold")`
- `hook_size: PositiveIntegerField(default=60)`
- `hook_color: CharField(max_length=9, default="#FFFFFF")`
- `hook_bg_color: CharField(max_length=9, default="#CC000000")` — semi-transparent black
- `hook_animation: CharField(choices=[POP, FADE, NONE], default=FADE)`

**Watermark fields:**
- `watermark_enabled: BooleanField(default=False)`
- `watermark_type: CharField(choices=[IMAGE, TEXT], default=TEXT)`
- `watermark_text: CharField(max_length=100, blank=True)` — e.g. "@channelname"
- `watermark_image: ImageField(upload_to="clipping/watermarks/", blank=True, null=True)`
- `watermark_position: CharField(choices=[TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT], default=BOTTOM_RIGHT)`
- `watermark_opacity: FloatField(default=0.6)` — 0.0–1.0
- `watermark_size: PositiveIntegerField(default=32)` — font size for text; px width for image

**Progress bar fields:**
- `progress_bar_enabled: BooleanField(default=False)`
- `progress_bar_position: CharField(choices=[TOP, BOTTOM], default=TOP)`
- `progress_bar_color: CharField(max_length=9, default="#FFFFFF")`
- `progress_bar_height: PositiveIntegerField(default=6)` — px

**Emoji accent fields:**
- `emoji_keyword_map: JSONField(default=dict, blank=True)` — maps keywords to emoji strings, e.g. `{"crazy": "🤯", "money": "💰", "fire": "🔥"}`. Applied during `EMOJI_ACCENT` caption generation. Channel provides defaults; `ClipStyleConfig` can override.

---

### 1.2 `ClipMediaAsset` (intro/outro library)

`ForeignKey` to `Channel`. Operator uploads files; `duration_sec` is auto-detected via ffprobe in a `pre_save` signal.

- `channel: ForeignKey(Channel, related_name="media_assets")`
- `asset_type: CharField(choices=[INTRO, OUTRO])`
- `name: CharField(max_length=200)`
- `file: FileField(upload_to="clipping/media_assets/")`
- `duration_sec: FloatField(null=True, blank=True)` — read-only, auto-detected
- `is_active: BooleanField(default=True)`

---

### 1.3 `ClipStyleConfig` (per-clip overrides)

`OneToOne` with `ClipCandidate`. Auto-created on `ClipCandidate.post_save` signal, pre-populated from the channel's `ClipRenderTemplate`.

Contains the same fields as `ClipRenderTemplate` (all caption, hook, watermark, progress bar fields) so any can be overridden per-clip. Additionally:

- `intro_asset: ForeignKey(ClipMediaAsset, null=True, blank=True, limit_choices_to={"asset_type": "INTRO"})`
- `outro_asset: ForeignKey(ClipMediaAsset, null=True, blank=True, limit_choices_to={"asset_type": "OUTRO"})`
- `preview_image: ImageField(upload_to="clipping/style_previews/", null=True, blank=True)`

**Population logic:** When created from the channel template, all fields are copied from `ClipRenderTemplate`. Fields left at their template value are not specially marked — the config is a standalone snapshot. Operator edits apply directly to `ClipStyleConfig`.

---

### 1.4 `ClipTimedOverlay` (multiple per clip)

`ForeignKey` to `ClipCandidate`. Operator adds rows in the admin. Start/end are in **rendered output time**: t=0 is the very first frame of the final file. If an intro is prepended (e.g. 3s) and a `TITLE_CARD` hook is added (e.g. 2s), then t=5 is the first frame of the main content. The operator sets these times by watching the completed render.

- `candidate: ForeignKey(ClipCandidate, related_name="timed_overlays")`
- `overlay_type: CharField(choices=[TEXT, IMAGE])`
- `text: CharField(max_length=300, blank=True)`
- `image: ImageField(upload_to="clipping/timed_overlays/", null=True, blank=True)`
- `start_sec: FloatField()`
- `end_sec: FloatField()`
- `position_x: PositiveIntegerField(default=540)` — px from left in output frame
- `position_y: PositiveIntegerField(default=960)` — px from top in output frame
- `opacity: FloatField(default=1.0)`
- `font_size: PositiveIntegerField(default=40)` — for TEXT type
- `font_color: CharField(max_length=9, default="#FFFFFF")` — for TEXT type

`clean()` validates `end_sec > start_sec`.

---

## 2. Renderer Architecture

### 2.1 `RenderStage` base class

```python
# reelforge/services/media/render_stages/base.py
from abc import ABC, abstractmethod
from pathlib import Path

class RenderStage(ABC):
    @abstractmethod
    def run(self, input_path: Path) -> Path:
        """Process input_path and return output path (may be same path if no-op)."""
        ...

    @property
    @abstractmethod
    def name(self) -> str: ...
```

Each stage either writes a new temp file and returns its path, or returns `input_path` unchanged (no-op). Temp files are tracked by the pipeline and cleaned up on completion or failure.

### 2.2 `ClipRenderPipeline`

Replaces `ClipRenderer` as the main rendering entry point.

```python
# reelforge/services/media/clip_render_pipeline.py
@dataclass
class PipelineRenderConfig:
    source_path: Path
    output_path: Path
    start_sec: float
    end_sec: float
    hook_text: str  # from ClipCandidate.hook_text
    transcript_json: dict[str, Any]  # from ClippingJob.transcript_json
    layout_config: ClipLayoutConfig | None
    style_config: ClipStyleConfig | None
    timed_overlays: list[ClipTimedOverlay]
    # render quality params
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = "slow"
    audio_bitrate: str = "192k"
```

The pipeline builds stages in order, runs them sequentially, moves the final output to `config.output_path`, then cleans all temp files.

### 2.3 Stage Order and Responsibilities

| # | Stage | File | Skipped when |
|---|-------|------|--------------|
| 1 | `TrimAndCropStage` | `trim_crop.py` | Never (always runs) |
| 2 | `IntroConcatStage` | `intro_outro.py` | `style_config.intro_asset` is None |
| 3 | `HookStage` | `hook.py` | `style_config.hook_enabled` is False or `hook_text` is empty |
| 4 | `CaptionStage` | `captions.py` | `style_config.caption_enabled` is False or no transcript |
| 5 | `WatermarkStage` | `watermark.py` | `style_config.watermark_enabled` is False |
| 6 | `TimedOverlayStage` | `timed_overlays.py` | `timed_overlays` list is empty |
| 7 | `ProgressBarStage` | `progress_bar.py` | `style_config.progress_bar_enabled` is False |
| 8 | `OutroConcatStage` | `intro_outro.py` | `style_config.outro_asset` is None |

All stage files live in `reelforge/services/media/render_stages/`.

### 2.4 Stage Details

**`TrimAndCropStage`**
Absorbs the existing `ClipRenderer._build_center_crop_command`, `_build_smart_crop_command`, and `_build_spatial_stack_command` logic. Output: trimmed + cropped 9:16 MP4.

**`IntroConcatStage` / `OutroConcatStage`**
Uses `ffmpeg concat demuxer` (file list approach) to join intro/outro with the main clip. Handles audio/video stream matching. Duration of the output increases by `intro.duration_sec` + `outro.duration_sec`.

**`HookStage`**
- `TITLE_CARD`: generates a black title card video (same dimensions as clip) using `ffmpeg lavfi color=black` + `drawtext`, then prepends it via concat. Duration increases by `hook_duration_sec`.
- `OVERLAY_TOP` / `OVERLAY_CENTER`: uses `drawtext` filter with `enable='lt(t,{hook_duration_sec})'` and a fade-out (`alpha` expression) to burn text over the first N seconds of the clip. No duration change.

**`CaptionStage`**
Generates an ASS subtitle file from `transcript_json`, then burns it with `-vf subtitles=file.ass:fontsdir=...`. The ASS generator is a separate `ASSGenerator` class in `captions.py` with a method per style:
- `WORD_BY_WORD`: one ASS event per word using `{\k}` karaoke tag; active word styled differently (color change).
- `CHUNKED`: groups words into 3–4 word chunks by natural pause boundaries; one event per chunk.
- `LOWER_THIRD`: one event per Whisper segment (full sentence); positioned at bottom with `\an2`.
- `EMOJI_ACCENT`: same as CHUNKED but post-processes text to insert emoji before high-energy words (uses a small keyword→emoji mapping configurable on the template).

Requires word-level timestamps in `transcript_json` (Whisper `word_timestamps=True`). Falls back to segment-level timing if word timestamps are absent.

**`WatermarkStage`**
- `TEXT` type: `drawtext` filter with opacity expression.
- `IMAGE` type: `overlay` filter with `format=auto` and alpha channel support. Image is scaled to `watermark_size` px width before overlaying.

**`TimedOverlayStage`**
Chains multiple filters in a single pass. For each `ClipTimedOverlay`:
- TEXT: `drawtext=text=...:enable='between(t,start,end)'`
- IMAGE: `[prev][img]overlay=x:y:enable='between(t,start,end)'`

All overlays are composited in a single ffmpeg invocation using `filter_complex`.

**`ProgressBarStage`**
Uses `drawbox` with width expression `w=W*t/duration` to draw a growing bar. Single `drawtext` pass.

---

## 3. Caption Implementation Detail

ASS subtitle format is used (not SRT) because it supports per-character styling, positioning, and karaoke tags needed for word-by-word style.

Font files must be available to ffmpeg. The project will maintain a `reelforge/static/fonts/` directory with the fonts referenced in caption configs. The `subtitles` filter `fontsdir` parameter points there.

Word timestamp extraction from `transcript_json` (Whisper format):
```python
# Each segment has a "words" list: [{"word": "...", "start": 1.2, "end": 1.8}, ...]
```
If `words` is absent (segment-only mode), `CaptionStage` falls back to displaying full segment text.

---

## 4. Admin Interface

### `ClipRenderTemplateInline` on `ChannelAdmin`
Stacked inline, collapsible. Fieldsets grouped by: Caption, Hook, Watermark, Progress Bar. All fields editable.

### `ClipMediaAssetAdmin`
Standalone registered admin. List display: name, channel, asset_type, duration_sec, is_active. Filter by channel + asset_type. `duration_sec` is read-only (auto-detected). File field shows a `<video>` preview tag.

### `ClipStyleConfigInline` on `ClipCandidateAdmin`
Stacked inline, collapsible. Same fieldsets as `ClipRenderTemplateInline` plus `intro_asset` and `outro_asset` dropdowns (filtered to the candidate's channel). `preview_image` shown as read-only thumbnail.

### `ClipTimedOverlayInline` on `ClipCandidateAdmin`
Tabular inline with `extra=0`. Fields: overlay_type, text/image, start_sec, end_sec, position_x, position_y, opacity. Operator adds/removes rows freely.

### New admin action: `"Generate style preview"`
On `ClipCandidateAdmin`. Queues `preview_clip_style` Celery task. The task:
1. Extracts a frame from mid-clip
2. Runs a lightweight version of `WatermarkStage`, `HookStage` (overlay styles only), and draws a caption text sample using PIL (not full ffmpeg render)
3. Saves result to `ClipStyleConfig.preview_image`

---

## 5. Task Changes

`render_clip` task in `tasks.py` is updated to:
1. Fetch `ClipStyleConfig` and `ClipTimedOverlay` queryset for the candidate
2. Build `PipelineRenderConfig` instead of `ClipRenderConfig`
3. Instantiate and run `ClipRenderPipeline` instead of `ClipRenderer`
4. Write back `last_speaker_crop_result` to `ClipLayoutConfig` (unchanged)

`ClipRenderConfig` and `ClipRenderer` are kept but deprecated — they remain functional for any existing callers until all callsites are migrated.

New task: `preview_clip_style(style_config_id: str)` — lightweight preview generation (see §4).

---

## 6. Migration Strategy

1. Add `ClipRenderTemplate`, `ClipMediaAsset`, `ClipStyleConfig`, `ClipTimedOverlay` models with migrations.
2. Write data migration to create `ClipRenderTemplate` for all existing `Channel` records.
3. Write data migration to create `ClipStyleConfig` for all existing `ClipCandidate` records (populated from channel template).
4. Update `post_save` signals for `Channel` (create `ClipRenderTemplate`) and `ClipCandidate` (create `ClipStyleConfig`).
5. Implement render stages in `reelforge/services/media/render_stages/`.
6. Implement `ClipRenderPipeline`.
7. Update `render_clip` task to use the pipeline.
8. Register admin classes.

---

## 7. Out of Scope

- Background music mixing (separate feature)
- Animated stickers / GIF overlays
- Multi-language caption translation
- Custom transitions between intro/clip/outro (hard cut only for now)
- Real-time preview in admin (static frame preview only)
