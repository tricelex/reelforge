from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from django.conf import settings
from django.utils import timezone

from reelforge.clipping.models import ClipRenderStageResult
from reelforge.core.storage import get_clip_ass_path
from reelforge.core.storage import get_stage_output_path
from reelforge.services.media.render_stages.base import RenderStageError

if TYPE_CHECKING:
    from reelforge.channels.models import Channel
    from reelforge.clipping.models import ClipLayoutConfig
    from reelforge.clipping.models import ClipStyleConfig

logger = logging.getLogger("reelforge.media.pipeline")


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

    def _build_stages(self) -> list:
        """Instantiate all 10 stages in order."""
        from reelforge.services.media.render_stages.captions import CaptionStage
        from reelforge.services.media.render_stages.captions import CaptionTranslationStage
        from reelforge.services.media.render_stages.hook import HookStage
        from reelforge.services.media.render_stages.intro_outro import IntroConcatStage
        from reelforge.services.media.render_stages.intro_outro import OutroConcatStage
        from reelforge.services.media.render_stages.music_mix import MusicMixStage
        from reelforge.services.media.render_stages.progress_bar import ProgressBarStage
        from reelforge.services.media.render_stages.timed_overlays import TimedOverlayStage
        from reelforge.services.media.render_stages.trim_crop import TrimAndCropStage
        from reelforge.services.media.render_stages.watermark import WatermarkStage

        c = self.config
        clip_duration = c.end_sec - c.start_sec
        static_root = getattr(settings, "STATIC_ROOT", None)
        if static_root:
            fonts_dir = Path(static_root) / "fonts"
        else:
            fonts_dir = Path(settings.BASE_DIR) / "reelforge" / "static" / "fonts"

        return [
            TrimAndCropStage(
                source_path=c.source_path,
                start_sec=c.start_sec,
                end_sec=c.end_sec,
                output_path=get_stage_output_path(c.render_id, 1, "trim_and_crop"),
                layout_config=c.layout_config,
                width=c.width,
                height=c.height,
                fps=c.fps,
                crf=c.crf,
                preset=c.preset,
                audio_bitrate=c.audio_bitrate,
            ),
            IntroConcatStage(
                output_path=get_stage_output_path(c.render_id, 2, "intro_concat"),
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
                output_path=get_stage_output_path(c.render_id, 3, "hook"),
                style_config=c.style_config,
                width=c.width,
                height=c.height,
                fps=c.fps,
                crf=c.crf,
                preset=c.preset,
                audio_bitrate=c.audio_bitrate,
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
                width=c.width,
                height=c.height,
                fps=c.fps,
                crf=c.crf,
                preset=c.preset,
                audio_bitrate=c.audio_bitrate,
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
        self._stages = stages
        current_path = self.config.source_path

        if start_from_stage > 1:
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
                    extra={
                        "render_id": self.config.render_id,
                        "start_from_stage": start_from_stage,
                    },
                )
            ClipRenderStageResult.objects.filter(
                render_id=self.config.render_id,
                stage_order__gte=start_from_stage,
            ).delete()

        for stage in stages:
            if stage.order < start_from_stage:
                continue
            current_path = self._run_stage(stage, current_path)

        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(current_path), str(self.config.output_path))
        logger.info(
            "ClipRenderPipeline completed",
            extra={"render_id": self.config.render_id, "output": str(self.config.output_path)},
        )
        return self.config.output_path

    def _run_stage(self, stage: Any, input_path: Path) -> Path:
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
                try:
                    result.output_file = str(
                        input_path.relative_to(Path(settings.MEDIA_ROOT))
                    )
                except ValueError:
                    pass  # path is outside MEDIA_ROOT (e.g. in tests)
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
            try:
                result.output_file = str(
                    output_path.relative_to(Path(settings.MEDIA_ROOT))
                )
            except ValueError:
                pass  # path is outside MEDIA_ROOT (e.g. in tests)
            result.save(
                update_fields=[
                    "status",
                    "completed_at",
                    "duration_sec",
                    "output_file",
                    "updated_at",
                ]
            )
            logger.info(
                "Stage completed",
                extra={
                    "stage": stage.name,
                    "duration_sec": duration,
                    "render_id": self.config.render_id,
                },
            )
            return output_path

        except Exception as exc:
            result.status = ClipRenderStageResult.Status.FAILED
            result.last_error = str(exc)
            result.completed_at = timezone.now()
            result.save(
                update_fields=["status", "last_error", "completed_at", "updated_at"]
            )
            logger.error(
                "Stage failed",
                extra={
                    "stage": stage.name,
                    "render_id": self.config.render_id,
                    "error": str(exc),
                },
            )
            raise RenderStageError(stage.name, stage.order, exc) from exc
