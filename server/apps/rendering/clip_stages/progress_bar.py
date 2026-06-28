"""ProgressBarStage — stage 8: animated progress bar overlay."""

from __future__ import annotations

import logging
import subprocess  # noqa: S404
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, final, override

from server.apps.clips.logic.constants import ProgressBarPosition
from server.apps.rendering.clip_stages.base import RenderStage
from server.apps.rendering.clip_stages.encode import clip_filter_encode_args

if TYPE_CHECKING:
    from server.apps.clips.models import ClipStyleConfig

logger = logging.getLogger('reelforge.rendering.clip_stages')


@final
@dataclass
class ProgressBarStage(RenderStage):
    """Stage 8: Animated progress bar overlay."""

    output_path: Path
    style_config: ClipStyleConfig | None
    video_duration_sec: float
    width: int = 1080
    crf: int = 18
    preset: str = 'slow'
    fps: int = 30
    audio_bitrate: str = '192k'

    @property
    @override
    def name(self) -> str:
        """Short identifier for this stage."""
        return 'progress_bar'

    @property
    @override
    def order(self) -> int:
        """Execution order (1-indexed)."""
        return 8

    @override
    def should_run(self) -> bool:
        """Return True if progress bar is enabled in style config."""
        return (
            self.style_config is not None
            and self.style_config.progress_bar_enabled
        )

    @override
    def run(self, input_path: Path) -> Path:
        """Draw animated progress bar on the clip."""
        sc = self.style_config
        assert sc is not None  # noqa: S101

        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        bar_height = sc.progress_bar_height
        color = sc.progress_bar_color.lstrip('#')
        dur = self.video_duration_sec
        y = (
            '0'
            if sc.progress_bar_position == ProgressBarPosition.TOP
            else 'H-h'
        )

        filter_complex = (
            f'color=c=0x{color}:size={self.width}x{bar_height}:rate={self.fps},'
            f"scale=eval=frame:w='max(2,{self.width}*t/{dur:.6f})'"
            f':h={bar_height}[bar];'
            f'[0:v][bar]overlay=x=0:y={y}:shortest=1[vout]'
        )
        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            str(input_path),
            '-filter_complex',
            filter_complex,
            '-map',
            '[vout]',
            '-map',
            '0:a?',
            *clip_filter_encode_args(
                crf=self.crf,
                preset=self.preset,
                fps=self.fps,
                audio_bitrate=self.audio_bitrate,
            ),
            str(self.output_path),
        ]
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f'ProgressBarStage ffmpeg failed: {result.stderr}',
            )
        return self.output_path
