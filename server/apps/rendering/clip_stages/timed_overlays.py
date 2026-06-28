"""TimedOverlayStage — stage 7: text or image overlays with time ranges."""

from __future__ import annotations

import logging
import subprocess  # noqa: S404
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, final, override

from server.apps.rendering.clip_stages.base import RenderStage
from server.apps.rendering.clip_stages.encode import clip_filter_encode_args

if TYPE_CHECKING:
    from server.apps.clips.models import ClipTimedOverlay

logger = logging.getLogger('reelforge.rendering.clip_stages')


@final
@dataclass
class TimedOverlayStage(RenderStage):
    """Stage 7: Apply timed text/image overlays."""

    output_path: Path
    timed_overlays: list[ClipTimedOverlay] = field(default_factory=list)
    crf: int = 18
    preset: str = 'slow'
    fps: int = 30
    audio_bitrate: str = '192k'

    @property
    @override
    def name(self) -> str:
        """Short identifier for this stage."""
        return 'timed_overlays'

    @property
    @override
    def order(self) -> int:
        """Execution order (1-indexed)."""
        return 7

    @override
    def should_run(self) -> bool:
        """Return True if there are overlays to apply."""
        return len(self.timed_overlays) > 0

    @override
    def run(self, input_path: Path) -> Path:
        """Apply all timed overlays using ffmpeg drawtext filter."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        vf_parts = []
        for overlay in self.timed_overlays:
            if overlay.text:
                safe = overlay.text.replace("'", "\\'").replace(':', '\\:')
                part = (
                    f"drawtext=text='{safe}'"
                    f':fontsize={overlay.font_size}'
                    f':fontcolor={overlay.color}@{overlay.opacity}'
                    f':x={overlay.x}:y={overlay.y}'
                    f":enable='between(t,{overlay.start_sec},{overlay.end_sec})'"
                )
                vf_parts.append(part)

        if not vf_parts:
            return input_path

        vf = ','.join(vf_parts)
        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            str(input_path),
            '-vf',
            vf,
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
                f'TimedOverlayStage ffmpeg failed: {result.stderr}',
            )
        return self.output_path
