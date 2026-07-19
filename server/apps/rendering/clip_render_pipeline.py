"""ClipRenderPipeline — orchestrates the 11-stage clip render pipeline."""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from server.apps.rendering.clip_stages.base import RenderStage, RenderStageError

if TYPE_CHECKING:
    from server.apps.clips.models import (
        ClipLayoutConfig,
        ClipStyleConfig,
        ClipTimedOverlay,
        ClipTimedSfx,
    )

logger = logging.getLogger('***REMOVED***.rendering.clip_render_pipeline')


class GatePausedException(Exception):  # noqa: N818
    """Raised when the pipeline is paused at a gate stage."""

    def __init__(self, stage_order: int) -> None:
        """Store the gate stage order that caused the pause."""
        self.stage_order = stage_order
        super().__init__(f'Render paused at gate after stage {stage_order}')


def _shift_time(
    value: Any,
    *,
    start_sec: float,
    clip_dur: float,
) -> float | None:
    """Shift an absolute timestamp into [0, clip_dur], or None if invalid."""
    try:
        absolute = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(absolute - start_sec, clip_dur))


def _rebase_timed_words(
    words: list[Any],
    *,
    start_sec: float,
    end_sec: float,
    clip_dur: float,
) -> list[dict[str, Any]]:
    """Filter and rebase word-level timestamps into the clip window."""
    rebased: list[dict[str, Any]] = []
    max_words = len(words)
    for idx, raw in enumerate(words):
        assert idx < max_words  # noqa: S101
        if not isinstance(raw, dict):
            continue
        try:
            word_start = float(raw.get('start', 0))
            word_end = float(raw.get('end', word_start))
        except (TypeError, ValueError):
            continue
        if word_end <= start_sec or word_start >= end_sec:
            continue
        new_start = _shift_time(
            word_start,
            start_sec=start_sec,
            clip_dur=clip_dur,
        )
        new_end = _shift_time(
            word_end,
            start_sec=start_sec,
            clip_dur=clip_dur,
        )
        if new_start is None or new_end is None or new_end <= new_start:
            continue
        rebased.append({**raw, 'start': new_start, 'end': new_end})
    return rebased


def _rebase_segment(
    seg: dict[str, Any],
    *,
    start_sec: float,
    end_sec: float,
    clip_dur: float,
) -> dict[str, Any] | None:
    """Rebase one transcript segment into the clip window, or None."""
    try:
        seg_start = float(seg.get('start', 0))
        seg_end = float(seg.get('end', seg_start))
    except (TypeError, ValueError):
        return None
    if seg_end <= start_sec or seg_start >= end_sec:
        return None
    new_start = _shift_time(
        seg_start,
        start_sec=start_sec,
        clip_dur=clip_dur,
    )
    new_end = _shift_time(
        seg_end,
        start_sec=start_sec,
        clip_dur=clip_dur,
    )
    if new_start is None or new_end is None or new_end <= new_start:
        return None
    new_seg = dict(seg)
    new_seg['start'] = new_start
    new_seg['end'] = new_end
    words = seg.get('words')
    if isinstance(words, list):
        new_seg['words'] = _rebase_timed_words(
            words,
            start_sec=start_sec,
            end_sec=end_sec,
            clip_dur=clip_dur,
        )
    return new_seg


def _rebase_transcript(
    transcript_json: dict[str, Any],
    *,
    start_sec: float,
    end_sec: float,
) -> dict[str, Any]:
    """Filter and shift transcript times into the trimmed clip timeline.

    Source transcripts use absolute times on the full video. After trim the
    output starts at t=0, so captions must be rebased by subtracting
    ``start_sec`` and clamped to ``[0, end_sec - start_sec]``.
    """
    clip_dur = max(0.0, end_sec - start_sec)
    result = dict(transcript_json)

    segments = transcript_json.get('segments', [])
    if isinstance(segments, list):
        rebased_segments: list[dict[str, Any]] = []
        max_segments = len(segments)
        for idx, seg in enumerate(segments):
            assert idx < max_segments  # noqa: S101
            if not isinstance(seg, dict):
                continue
            rebased = _rebase_segment(
                seg,
                start_sec=start_sec,
                end_sec=end_sec,
                clip_dur=clip_dur,
            )
            if rebased is not None:
                rebased_segments.append(rebased)
        result['segments'] = rebased_segments

    top_words = transcript_json.get('words')
    if isinstance(top_words, list):
        result['words'] = _rebase_timed_words(
            top_words,
            start_sec=start_sec,
            end_sec=end_sec,
            clip_dur=clip_dur,
        )
    return result


def _scale_transcript(
    transcript_json: dict[str, Any],
    *,
    playback_speed: float,
) -> dict[str, Any]:
    """Scale caption/hook timestamps to match a sped-up/slowed-down clip."""
    if abs(playback_speed - 1.0) < 1e-9:
        return transcript_json
    factor = 1.0 / playback_speed
    scaled_segments = []
    for seg in transcript_json.get('segments', []):
        new_seg = dict(seg)
        new_seg['start'] = seg['start'] * factor
        new_seg['end'] = seg['end'] * factor
        if 'words' in seg:
            new_seg['words'] = [
                {**w, 'start': w['start'] * factor, 'end': w['end'] * factor}
                for w in seg['words']
            ]
        scaled_segments.append(new_seg)
    result = {**transcript_json, 'segments': scaled_segments}
    top_words = transcript_json.get('words')
    if isinstance(top_words, list):
        result['words'] = [
            {**w, 'start': w['start'] * factor, 'end': w['end'] * factor}
            for w in top_words
            if isinstance(w, dict)
        ]
    return result


@dataclass
class PipelineRenderConfig:
    """All parameters needed to render one clip candidate."""

    source_path: Path
    output_path: Path
    start_sec: float
    end_sec: float
    hook_text: str
    transcript_json: dict[str, Any]
    layout_config: ClipLayoutConfig | None
    style_config: ClipStyleConfig | None
    timed_overlays: list[ClipTimedOverlay] = field(default_factory=list)
    timed_sfx: list[ClipTimedSfx] = field(default_factory=list)
    render_id: str = ''
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = 'slow'
    audio_bitrate: str = '192k'


class ClipRenderPipeline:
    """Synchronous 11-stage clip render orchestrator.

    Each stage reads the current working file, processes it, and outputs a new
    file. Stages that return should_run()=False are skipped and the current path
    passes through unchanged.

    Run via asyncio.to_thread() from async TaskIQ workers.
    """

    def __init__(self, config: PipelineRenderConfig) -> None:
        """Initialise with a render config."""
        self.config = config

    def _build_stages(self) -> list[RenderStage]:
        from server.apps.rendering.clip_stages.captions import (  # noqa: PLC0415
            CaptionStage,
            CaptionTranslationStage,
        )
        from server.apps.rendering.clip_stages.color_grade import (  # noqa: PLC0415
            ColorGradeStage,
        )
        from server.apps.rendering.clip_stages.fonts import (  # noqa: PLC0415
            build_fonts_dir,
        )
        from server.apps.rendering.clip_stages.hook import (  # noqa: PLC0415
            HookStage,
        )
        from server.apps.rendering.clip_stages.intro_outro import (  # noqa: PLC0415
            IntroConcatStage,
            OutroConcatStage,
        )
        from server.apps.rendering.clip_stages.music_mix import (  # noqa: PLC0415
            MusicMixStage,
        )
        from server.apps.rendering.clip_stages.progress_bar import (  # noqa: PLC0415
            ProgressBarStage,
        )
        from server.apps.rendering.clip_stages.timed_overlays import (  # noqa: PLC0415
            TimedOverlayStage,
        )
        from server.apps.rendering.clip_stages.trim_crop import (  # noqa: PLC0415
            TrimAndCropStage,
        )
        from server.apps.rendering.clip_stages.watermark import (  # noqa: PLC0415
            WatermarkStage,
        )

        c = self.config
        clip_dur = c.end_sec - c.start_sec
        render_dir = c.render_id or 'default'
        tmp = Path(tempfile.gettempdir()) / 'clip_renders' / render_dir
        tmp.mkdir(parents=True, exist_ok=True)

        playback_speed = (
            c.style_config.playback_speed if c.style_config else 1.0
        )
        transcript_json = _scale_transcript(
            _rebase_transcript(
                c.transcript_json,
                start_sec=c.start_sec,
                end_sec=c.end_sec,
            ),
            playback_speed=playback_speed,
        )
        font_assets: list = []
        if c.style_config is not None:
            sc = c.style_config
            font_assets = [
                sc.caption_font_asset,
                sc.hook_font_asset,
                sc.watermark_font_asset,
            ]
            for ov in c.timed_overlays:
                font_assets.append(ov.font_asset)
        fonts_dir = build_fonts_dir(tmp, font_assets)

        return [
            TrimAndCropStage(
                source_path=c.source_path,
                start_sec=c.start_sec,
                end_sec=c.end_sec,
                output_path=tmp / '01_trim_crop.mp4',
                layout_config=c.layout_config,
                width=c.width,
                height=c.height,
                fps=c.fps,
                crf=c.crf,
                preset=c.preset,
                audio_bitrate=c.audio_bitrate,
                playback_speed=playback_speed,
            ),
            ColorGradeStage(
                output_path=tmp / '02_color_grade.mp4',
                style_config=c.style_config,
                crf=c.crf,
                preset=c.preset,
                fps=c.fps,
                audio_bitrate=c.audio_bitrate,
            ),
            IntroConcatStage(
                output_path=tmp / '03_intro.mp4',
                style_config=c.style_config,
                width=c.width,
                height=c.height,
                fps=c.fps,
                crf=c.crf,
                preset=c.preset,
                audio_bitrate=c.audio_bitrate,
            ),
            HookStage(
                hook_text=c.hook_text,
                output_path=tmp / '04_hook.mp4',
                style_config=c.style_config,
                crf=c.crf,
                preset=c.preset,
                width=c.width,
                height=c.height,
                fps=c.fps,
                audio_bitrate=c.audio_bitrate,
            ),
            CaptionTranslationStage(
                transcript_json=transcript_json,
                output_path=tmp / '05_caption_translation.mp4',
                style_config=c.style_config,
            ),
            CaptionStage(
                transcript_json=transcript_json,
                output_path=tmp / '06_captions.mp4',
                ass_path=tmp / 'captions.ass',
                style_config=c.style_config,
                fonts_dir=fonts_dir,
                video_width=c.width,
                video_height=c.height,
                crf=c.crf,
                preset=c.preset,
                fps=c.fps,
                audio_bitrate=c.audio_bitrate,
            ),
            WatermarkStage(
                output_path=tmp / '07_watermark.mp4',
                style_config=c.style_config,
                crf=c.crf,
                preset=c.preset,
                fps=c.fps,
                audio_bitrate=c.audio_bitrate,
            ),
            TimedOverlayStage(
                output_path=tmp / '08_timed_overlays.mp4',
                timed_overlays=c.timed_overlays,
                crf=c.crf,
                preset=c.preset,
                fps=c.fps,
                audio_bitrate=c.audio_bitrate,
            ),
            ProgressBarStage(
                output_path=tmp / '09_progress_bar.mp4',
                style_config=c.style_config,
                video_duration_sec=clip_dur,
                width=c.width,
                crf=c.crf,
                preset=c.preset,
                fps=c.fps,
                audio_bitrate=c.audio_bitrate,
            ),
            OutroConcatStage(
                output_path=tmp / '10_outro.mp4',
                style_config=c.style_config,
                width=c.width,
                height=c.height,
                fps=c.fps,
                crf=c.crf,
                preset=c.preset,
                audio_bitrate=c.audio_bitrate,
            ),
            MusicMixStage(
                output_path=tmp / '11_music_and_sfx.mp4',
                style_config=c.style_config,
                video_duration_sec=clip_dur,
                timed_sfx=c.timed_sfx,
            ),
        ]

    def run(
        self,
        start_from_stage: int = 1,
        pause_after_stages: set[int] | None = None,
    ) -> Path:
        """Execute stages in order; return final output path.

        Args:
            start_from_stage: Resume from this stage number (1-indexed).
            pause_after_stages: If a stage's order is in this set, raise
                GatePausedException after it completes.
        """
        stages = self._build_stages()
        current_path = self.config.source_path
        gates = pause_after_stages or set()

        for stage in stages:
            if stage.order < start_from_stage:
                continue
            if stage.should_run():
                current_path = self._run_stage(stage, current_path)
            else:
                logger.debug('Stage %d (%s) skipped', stage.order, stage.name)
            if stage.order in gates:
                raise GatePausedException(stage_order=stage.order)

        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(current_path), str(self.config.output_path))
        logger.info('ClipRenderPipeline completed: %s', self.config.output_path)
        return self.config.output_path

    def _run_stage(self, stage: RenderStage, input_path: Path) -> Path:
        try:
            output = stage.run(input_path)
        except RenderStageError:
            raise
        except Exception as exc:
            raise RenderStageError(stage.name, stage.order, exc) from exc
        else:
            logger.info('Stage %d (%s) completed', stage.order, stage.name)
            return output
