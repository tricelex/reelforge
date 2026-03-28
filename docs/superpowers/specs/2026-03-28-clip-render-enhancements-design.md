# Clip Render Enhancements — Design Spec

**Date:** 2026-03-28
**Status:** Approved
**Scope:** Captions, hook overlays, intro/outro library, watermarks, timed overlays, progress bar,
per-stage tracking + retry, custom transitions, multi-language caption translation, background music

---

## Overview

Enhance the clipping pipeline to support CapCut-level per-clip personalisation: styled captions,
hook text overlays, channel intro/outro library, persistent watermarks, time-ranged overlays,
progress bar, background music, and custom transitions. All features support **channel-level
defaults** with **per-clip overrides**.

The renderer is refactored from a single FFmpeg command builder into a **multi-stage pipeline**
where each stage writes a persistent output file. The operator can inspect the result of every
stage in the admin and retry from any failed or unwanted stage forward.

---

## 1. Data Models

### 1.1 `ClipRenderTemplate` (channel level defaults)

`OneToOne` with `Channel`. Auto-created when a `Channel` is saved (via `post_save` signal).

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
- `caption_language: CharField(max_length=10, default="en")` — BCP-47 language code of source audio
- `caption_translate_to: CharField(max_length=10, blank=True)` — if set, translate captions to this language before rendering (e.g. "es", "fr", "pt"). Empty = no translation.

**Emoji accent fields:**
- `emoji_keyword_map: JSONField(default=dict, blank=True)` — maps keywords to emoji strings, e.g. `{"crazy": "🤯", "money": "💰", "fire": "🔥"}`. Applied during `EMOJI_ACCENT` caption generation.

**Hook fields:**
- `hook_enabled: BooleanField(default=True)`
- `hook_style: CharField(choices=[TITLE_CARD, OVERLAY_TOP, OVERLAY_CENTER], default=OVERLAY_TOP)`
- `hook_duration_sec: FloatField(default=2.5)` — how long the hook text displays
- `hook_font: CharField(max_length=100, default="Montserrat-Bold")`
- `hook_size: PositiveIntegerField(default=60)`
- `hook_color: CharField(max_length=9, default="#FFFFFF")`
- `hook_bg_color: CharField(max_length=9, default="#CC000000")` — semi-transparent black
- `hook_animation: CharField(choices=[POP, FADE, NONE], default=FADE)`

**Transition fields:**
- `intro_transition: CharField(choices=[NONE, CROSSFADE, FADE_BLACK, WIPE_LEFT, WIPE_RIGHT], default=NONE)`
- `outro_transition: CharField(choices=[NONE, CROSSFADE, FADE_BLACK, WIPE_LEFT, WIPE_RIGHT], default=NONE)`
- `transition_duration_sec: FloatField(default=0.5)` — applies to both intro and outro transitions

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

**Background music fields:**
- `music_enabled: BooleanField(default=False)`
- `music_volume_db: FloatField(default=-20.0)` — dB relative to original audio (negative = quieter)
- `music_fade_in_sec: FloatField(default=1.0)`
- `music_fade_out_sec: FloatField(default=1.0)`

---

### 1.2 `ClipMediaAsset` (intro/outro library)

`ForeignKey` to `Channel`. Operator uploads files; `duration_sec` is auto-detected via ffprobe in a `pre_save` signal.

- `channel: ForeignKey(Channel, related_name="media_assets")`
- `asset_type: CharField(choices=[INTRO, OUTRO])`
- `name: CharField(max_length=200)`
- `file: FileField(upload_to="clipping/media_assets/", max_length=500)`
- `duration_sec: FloatField(null=True, blank=True)` — read-only, auto-detected
- `is_active: BooleanField(default=True)`

---

### 1.3 `ClipMusicAsset` (background music library)

`ForeignKey` to `Channel`. Music files (MP3/WAV) available for mixing under clips.

- `channel: ForeignKey(Channel, related_name="music_assets")`
- `name: CharField(max_length=200)`
- `file: FileField(upload_to="clipping/music_assets/", max_length=500)`
- `duration_sec: FloatField(null=True, blank=True)` — auto-detected via ffprobe on save
- `bpm: FloatField(null=True, blank=True)` — optional, informational
- `genre: CharField(max_length=100, blank=True)`
- `is_active: BooleanField(default=True)`

---

### 1.4 `ClipStyleConfig` (per-clip overrides)

`OneToOne` with `ClipCandidate`. Auto-created on `ClipCandidate.post_save` signal, pre-populated from the channel's `ClipRenderTemplate`.

Contains the same fields as `ClipRenderTemplate` (all caption, hook, transition, watermark,
progress bar, and music fields) so any can be overridden per-clip. Additionally:

- `intro_asset: ForeignKey(ClipMediaAsset, null=True, blank=True, limit_choices_to={"asset_type": "INTRO"})`
- `outro_asset: ForeignKey(ClipMediaAsset, null=True, blank=True, limit_choices_to={"asset_type": "OUTRO"})`
- `music_asset: ForeignKey(ClipMusicAsset, null=True, blank=True)`
- `translated_transcript_json: JSONField(default=dict, blank=True)` — cached output of `CaptionTranslationStage`; avoids re-translating on caption-only retries
- `preview_image: ImageField(upload_to="clipping/style_previews/", null=True, blank=True)`

**Population logic:** When created, all fields are copied from the channel's `ClipRenderTemplate`.
Operator edits apply directly to `ClipStyleConfig` without affecting the template.

---

### 1.5 `ClipTimedOverlay` (multiple per clip)

`ForeignKey` to `ClipCandidate`. Start/end are in **rendered output time**: t=0 is the very first
frame of the final file. If an intro is prepended (e.g. 3s) and a `TITLE_CARD` hook is added
(e.g. 2s), then t=5 is the first frame of the main content. The operator sets these times by
watching the completed render.

- `candidate: ForeignKey(ClipCandidate, related_name="timed_overlays")`
- `overlay_type: CharField(choices=[TEXT, IMAGE])`
- `text: CharField(max_length=300, blank=True)`
- `image: ImageField(upload_to="clipping/timed_overlays/", null=True, blank=True, max_length=500)`
- `start_sec: FloatField()`
- `end_sec: FloatField()`
- `position_x: PositiveIntegerField(default=540)` — px from left in output frame
- `position_y: PositiveIntegerField(default=960)` — px from top in output frame
- `opacity: FloatField(default=1.0)`
- `font_size: PositiveIntegerField(default=40)` — for TEXT type
- `font_color: CharField(max_length=9, default="#FFFFFF")` — for TEXT type

`clean()` validates `end_sec > start_sec`.

---

### 1.6 `ClipRenderStageResult` (per-stage tracking)

`ForeignKey` to `ClipRender`. One record per stage per render. Created by the pipeline before
each stage runs, updated on completion or failure. Enables per-stage inspection and retry.

- `render: ForeignKey(ClipRender, related_name="stage_results")`
- `stage_name: CharField(max_length=100)` — e.g. `"trim_and_crop"`, `"captions"`, `"watermark"`
- `stage_order: PositiveIntegerField()` — position in pipeline (1-based)
- `status: CharField(choices=[PENDING, RUNNING, COMPLETED, FAILED, SKIPPED])`
- `output_file: FileField(upload_to="clipping/stage_outputs/", null=True, blank=True, max_length=500)` — the video file produced by this stage
- `started_at: DateTimeField(null=True, blank=True)`
- `completed_at: DateTimeField(null=True, blank=True)`
- `duration_sec: FloatField(null=True, blank=True)`
- `last_error: TextField(blank=True)`

Stage output files are stored at `clipping/stage_outputs/{render_id}/{stage_order:02d}_{stage_name}.mp4`.
They persist until the operator deletes the `ClipRender` or explicitly clears them.

---

## 2. Renderer Architecture

### 2.1 `RenderStage` base class

```python
# reelforge/services/media/render_stages/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path

class RenderStage(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def order(self) -> int: ...

    def should_run(self) -> bool:
        """Return False to mark this stage as SKIPPED."""
        return True

    @abstractmethod
    def run(self, input_path: Path) -> Path:
        """Process input_path, write output to a new file, return its path."""
        ...
```

Each stage writes its output to a persistent named file (not a temp file). If `should_run()`
returns False, the stage is marked SKIPPED and `input_path` is passed through to the next stage.

### 2.2 `ClipRenderPipeline`

```python
# reelforge/services/media/clip_render_pipeline.py
@dataclass
class PipelineRenderConfig:
    source_path: Path
    output_path: Path
    start_sec: float
    end_sec: float
    hook_text: str                        # from ClipCandidate.hook_text
    transcript_json: dict[str, Any]       # from ClippingJob.transcript_json
    layout_config: ClipLayoutConfig | None
    style_config: ClipStyleConfig | None
    timed_overlays: list[ClipTimedOverlay]
    render_id: str                        # ClipRender.id — for stage output paths
    # render quality params
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = "slow"
    audio_bitrate: str = "192k"
```

The pipeline:
1. Builds all stages in order
2. For each stage: creates/updates `ClipRenderStageResult`, calls `stage.run(current_path)`,
   updates the result with output path and status
3. On any stage failure: marks that stage FAILED, stops the pipeline, raises
4. On success: moves the final stage output to `config.output_path`

**Retry from stage N**: The `render_clip` task accepts an optional `start_from_stage: int = 1`
parameter. When retrying, it deletes `ClipRenderStageResult` records for stages ≥ N, then uses
the output of stage N-1 as the starting `input_path`. Stage 1 always starts from the source video.

### 2.3 Stage Order and Responsibilities

| # | Stage | File | Skipped when |
|---|-------|------|--------------|
| 1 | `TrimAndCropStage` | `trim_crop.py` | Never |
| 2 | `IntroConcatStage` | `intro_outro.py` | `style_config.intro_asset` is None |
| 3 | `HookStage` | `hook.py` | `hook_enabled` is False or `hook_text` is empty |
| 4 | `CaptionTranslationStage` | `captions.py` | `caption_translate_to` is blank |
| 5 | `CaptionStage` | `captions.py` | `caption_enabled` is False or no transcript |
| 6 | `WatermarkStage` | `watermark.py` | `watermark_enabled` is False |
| 7 | `TimedOverlayStage` | `timed_overlays.py` | `timed_overlays` list is empty |
| 8 | `ProgressBarStage` | `progress_bar.py` | `progress_bar_enabled` is False |
| 9 | `OutroConcatStage` | `intro_outro.py` | `style_config.outro_asset` is None |
| 10 | `MusicMixStage` | `music_mix.py` | `music_enabled` is False or `music_asset` is None |

All stage files live in `reelforge/services/media/render_stages/`.

### 2.4 Stage Details

**`TrimAndCropStage`**
Absorbs the existing `ClipRenderer._build_center_crop_command`, `_build_smart_crop_command`, and
`_build_spatial_stack_command` logic. Output: trimmed + cropped 9:16 MP4.

**`IntroConcatStage` / `OutroConcatStage`**
When `transition == NONE`: uses `ffmpeg concat demuxer` (file list approach) for a hard cut join.
When `transition != NONE`: uses `ffmpeg xfade` filter:
- `CROSSFADE` → `xfade=transition=fade`
- `FADE_BLACK` → `xfade=transition=fadeblack`
- `WIPE_LEFT` → `xfade=transition=wipeleft`
- `WIPE_RIGHT` → `xfade=transition=wiperight`
`transition_duration_sec` is passed as the `duration` parameter. Both intro and outro use the
same `transition_duration_sec` from `ClipStyleConfig`. The xfade offset is calculated as
`intro_duration - transition_duration_sec`.

**`HookStage`**
- `TITLE_CARD`: generates a black title card video (same dimensions) via `ffmpeg lavfi color=black`
  + `drawtext`, then prepends via concat. Duration increases by `hook_duration_sec`.
- `OVERLAY_TOP` / `OVERLAY_CENTER`: uses `drawtext` with `enable='lt(t,{hook_duration_sec})'`
  and a fade-out alpha expression. No duration change.

**`CaptionTranslationStage`**
If `caption_translate_to` is set, translates the `transcript_json` word/segment text using
`get_llm_provider(channel)`. Produces a new `transcript_json`-shaped dict with translated text
but original timestamps preserved. This translated transcript is passed to `CaptionStage`.
Translation is cached on `ClipStyleConfig.translated_transcript_json: JSONField` so retrying
`CaptionStage` alone doesn't re-translate.

**`CaptionStage`**
Generates an ASS subtitle file from the (possibly translated) `transcript_json`, then burns it
with `-vf subtitles=file.ass:fontsdir=...`. The `ASSGenerator` class handles all 4 styles:
- `WORD_BY_WORD`: one ASS event per word using `{\k}` karaoke tag; active word highlighted.
- `CHUNKED`: groups words into 3–4 word chunks; one event per chunk.
- `LOWER_THIRD`: one event per Whisper segment, positioned at bottom with `\an2`.
- `EMOJI_ACCENT`: same as CHUNKED but post-processes text against `emoji_keyword_map`.
Falls back to segment-level timing when word timestamps are absent.

**`WatermarkStage`**
- `TEXT` type: `drawtext` filter with opacity.
- `IMAGE` type: `overlay` filter with `format=auto` for alpha channel support. Image scaled to
  `watermark_size` px width.

**`TimedOverlayStage`**
All overlays composited in a single ffmpeg pass using `filter_complex`:
- TEXT: `drawtext=text=...:enable='between(t,start,end)'`
- IMAGE: `[prev][img]overlay=x:y:enable='between(t,start,end)'`

**`ProgressBarStage`**
`drawbox` with a time-driven width expression: `w=W*t/duration`. Single ffmpeg pass.

**`MusicMixStage`**
Runs last so it applies to the full assembled output (intro + content + outro). Uses ffmpeg
`amix` filter to blend the music track with the existing audio:
1. If `music_asset.duration_sec < clip_duration`: loop the music using `-stream_loop -1`
2. Apply `music_volume_db` using a `volume` audio filter
3. Apply fade-in/fade-out using `afade` filter at start and end
4. Mix with original audio using `amix=inputs=2:duration=first:dropout_transition=0`
Target loudness: the music track is mixed to be `music_volume_db` dB below the original
audio's measured dBFS (measured via ffmpeg `volumedetect` before mixing).

---

## 3. Caption Implementation Detail

ASS subtitle format is used (not SRT) because it supports per-character styling, positioning,
and karaoke tags needed for word-by-word style.

Font files live in `reelforge/static/fonts/`. The `subtitles` filter `fontsdir` parameter points
there. `Montserrat-Bold.ttf` must be present at minimum.

**Translation:** `CaptionTranslationStage` calls `get_llm_provider(channel)` with a structured
prompt requesting JSON output that preserves the original `transcript_json` shape but replaces
all `text`/`word` fields with the translated equivalents. Timestamps are not translated.
Result is stored in `ClipStyleConfig.translated_transcript_json` to avoid re-translating on
stage retries.

---

## 4. Admin Interface

### `ClipRenderTemplateInline` on `ChannelAdmin`
Stacked inline, collapsible. Fieldsets: Caption, Emoji Accent, Hook, Transitions, Watermark,
Progress Bar, Background Music. All fields editable.

### `ClipMediaAssetAdmin`
Standalone registered admin. List: name, channel, asset_type, duration_sec, is_active.
Filter by channel + asset_type. `duration_sec` read-only. File field shows `<video>` preview.

### `ClipMusicAssetAdmin`
Standalone registered admin. List: name, channel, genre, duration_sec, bpm, is_active.
Filter by channel + genre. File field shows `<audio>` preview tag.

### `ClipStyleConfigInline` on `ClipCandidateAdmin`
Stacked inline, collapsible. Same fieldsets as `ClipRenderTemplateInline` plus `intro_asset`,
`outro_asset`, `music_asset` dropdowns (FK dropdowns filtered to the candidate's channel via
`get_queryset` override). `preview_image` shown as read-only thumbnail.

### `ClipTimedOverlayInline` on `ClipCandidateAdmin`
Tabular inline, `extra=0`. Fields: overlay_type, text/image, start_sec, end_sec, position_x,
position_y, opacity. Operator adds/removes rows freely.

### `ClipRenderStageResultInline` on `ClipRenderAdmin` (new)
Read-only tabular inline showing all stage results for a render:
- Columns: stage_order, stage_name, status badge (colour-coded), duration_sec, video_preview,
  last_error
- `video_preview`: renders a `<video>` tag with the stage output file when status=COMPLETED
- Cannot add or delete rows (pipeline manages lifecycle)

### `ClipRenderAdmin` (new or extend existing)
Registers `ClipRender` with `ClipRenderStageResultInline`. Admin actions:

**`"Retry from selected stage"`**
Available as a per-stage action on `ClipRenderStageResultInline` rows (via a custom change view
button, since Django inline actions are limited). Alternatively exposed as an admin action on
`ClipRenderAdmin` that prompts for stage number. Calls `render_clip.delay(candidate_id,
start_from_stage=N)`.

**`"Retry full render"`**
Existing-style action on `ClipCandidateAdmin`. Deletes all `ClipRenderStageResult` records for
the latest render and re-queues from stage 1.

**`"Clear stage outputs"`**
Deletes all stage output files and `ClipRenderStageResult` records for selected renders (to
free storage after the final output has been approved).

### New admin action: `"Generate style preview"`
On `ClipCandidateAdmin`. Queues `preview_clip_style` Celery task. The task:
1. Extracts a frame from mid-clip via OpenCV
2. Applies a lightweight PIL-based render of watermark text/image, hook overlay text, and a
   sample caption line (no full ffmpeg render)
3. Saves result to `ClipStyleConfig.preview_image`

---

## 5. Task Changes

### `render_clip` task

Updated signature: `render_clip(self, clip_candidate_id: str, start_from_stage: int = 1) -> None`

Steps:
1. Fetch `ClipStyleConfig`, `ClipTimedOverlay` queryset, `ClippingJob` for the candidate
2. When `start_from_stage > 1`: load input path from the output of stage `start_from_stage - 1`'s
   `ClipRenderStageResult`; delete stage results for stages ≥ `start_from_stage`
3. Build `PipelineRenderConfig`
4. Instantiate and run `ClipRenderPipeline`
5. Write back `last_speaker_crop_result` to `ClipLayoutConfig` (unchanged)

### New task: `preview_clip_style`

`preview_clip_style(style_config_id: str) -> None`
Lightweight single-frame preview. Uses PIL/OpenCV (no ffmpeg), completes in under 5 seconds.
Queue: `clipping`. Time limit: 60s.

### `ClipRenderConfig` / `ClipRenderer` deprecation

Kept functional for existing callsites. A deprecation warning is logged when `ClipRenderer` is
instantiated. Will be removed after all callsites are migrated to `ClipRenderPipeline`.

---

## 6. Migration Strategy

1. Add `ClipRenderTemplate`, `ClipMediaAsset`, `ClipMusicAsset`, `ClipStyleConfig`,
   `ClipTimedOverlay`, `ClipRenderStageResult` models with auto-generated migrations.
2. Data migration: create `ClipRenderTemplate` for all existing `Channel` records (defaults only).
3. Data migration: create `ClipStyleConfig` for all existing `ClipCandidate` records (copied
   from channel template).
4. Update `post_save` signals:
   - `Channel` → create `ClipRenderTemplate` if not exists
   - `ClipCandidate` → create `ClipStyleConfig` if not exists
5. Implement render stages in `reelforge/services/media/render_stages/`.
6. Implement `ClipRenderPipeline` in `reelforge/services/media/clip_render_pipeline.py`.
7. Update `render_clip` task signature and implementation.
8. Register new and updated admin classes.
9. Add `Montserrat-Bold.ttf` to `reelforge/static/fonts/` (required for captions).

---

## 7. Out of Scope

- Animated stickers / GIF overlays
- Real-time preview in admin (static frame preview only)
- Per-word emoji auto-detection via NLP (keyword map is manually configured)
- YouTube chapter markers from transcript (separate distribution feature)
