from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from reelforge.services.media.render_stages.base import RenderStage

if TYPE_CHECKING:
    from reelforge.clipping.models import ClipStyleConfig

logger = logging.getLogger("reelforge.media.render_stages")


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
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "slow",
            "-c:a",
            "copy",
            "-movflags",
            "faststart",
            str(self.output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"ProgressBarStage failed: {result.stderr}")
        logger.info("ProgressBarStage completed", extra={"output": str(self.output_path)})
        return self.output_path
