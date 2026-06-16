"""ClipRenderPipeline — orchestrates the 10-stage clip render pipeline."""

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
    )

logger = logging.getLogger('reelforge.rendering.clip_render_pipeline')


class GatePausedException(Exception):  # noqa: N818
    """Raised when the pipeline is paused at a gate stage."""

    def __init__(self, stage_order: int) -> None:
        """Store the gate stage order that caused the pause."""
        self.stage_order = stage_order
        super().__init__(f'Render paused at gate after stage {stage_order}')


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
    render_id: str = ''
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = 'slow'
    audio_bitrate: str = '192k'


class ClipRenderPipeline:
    """Synchronous 10-stage clip render orchestrator.

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
            ),
            IntroConcatStage(
                output_path=tmp / '02_intro.mp4',
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
                output_path=tmp / '03_hook.mp4',
                style_config=c.style_config,
                crf=c.crf,
                preset=c.preset,
            ),
            CaptionTranslationStage(
                transcript_json=c.transcript_json,
                output_path=tmp / '04_caption_translation.mp4',
                style_config=c.style_config,
            ),
            CaptionStage(
                transcript_json=c.transcript_json,
                output_path=tmp / '05_captions.mp4',
                ass_path=tmp / 'captions.ass',
                style_config=c.style_config,
                video_width=c.width,
                video_height=c.height,
                crf=c.crf,
                preset=c.preset,
            ),
            WatermarkStage(
                output_path=tmp / '06_watermark.mp4',
                style_config=c.style_config,
                crf=c.crf,
                preset=c.preset,
            ),
            TimedOverlayStage(
                output_path=tmp / '07_timed_overlays.mp4',
                timed_overlays=c.timed_overlays,
                crf=c.crf,
                preset=c.preset,
            ),
            ProgressBarStage(
                output_path=tmp / '08_progress_bar.mp4',
                style_config=c.style_config,
                video_duration_sec=clip_dur,
                crf=c.crf,
                preset=c.preset,
            ),
            OutroConcatStage(
                output_path=tmp / '09_outro.mp4',
                style_config=c.style_config,
                width=c.width,
                height=c.height,
                fps=c.fps,
                crf=c.crf,
                preset=c.preset,
                audio_bitrate=c.audio_bitrate,
            ),
            MusicMixStage(
                output_path=tmp / '10_music.mp4',
                style_config=c.style_config,
                video_duration_sec=clip_dur,
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
