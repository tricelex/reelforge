from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from reelforge.services.media.render_stages.base import RenderStage

if TYPE_CHECKING:
    from pathlib import Path

    from reelforge.clipping.models import ClipStyleConfig

logger = logging.getLogger("reelforge.media.render_stages")

_POSITION_COORDS: dict[str, tuple[str, str]] = {
    "TOP_LEFT": ("10", "10"),
    "TOP_RIGHT": ("W-w-10", "10"),
    "BOTTOM_LEFT": ("10", "H-h-10"),
    "BOTTOM_RIGHT": ("W-w-10", "H-h-10"),
}


@dataclass
class WatermarkStage(RenderStage):
    """Stage 6: Add persistent watermark (text or image) to the video."""

    output_path: Path
    style_config: ClipStyleConfig | None
    crf: int = 18
    preset: str = "slow"

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
            msg = f"WatermarkStage failed: {result.stderr}"
            raise RuntimeError(msg)
        logger.info("WatermarkStage completed", extra={"output": str(self.output_path)})
        return self.output_path

    def _text_command(self, input_path: Path, sc: ClipStyleConfig) -> list[str]:
        x, y = _POSITION_COORDS.get(sc.watermark_position, ("W-w-10", "H-h-10"))
        text = sc.watermark_text.replace("'", "\\'").replace(":", "\\:")
        alpha = sc.watermark_opacity
        vf = (
            f"drawtext=text='{text}'"
            f":fontsize={sc.watermark_size}"
            f":fontcolor=white@{alpha}"
            f":x={x}:y={y}"
        )
        return [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-crf",
            str(self.crf),
            "-preset",
            self.preset,
            "-c:a",
            "copy",
            "-movflags",
            "faststart",
            str(self.output_path),
        ]

    def _image_command(self, input_path: Path, sc: ClipStyleConfig) -> list[str]:
        x, y = _POSITION_COORDS.get(sc.watermark_position, ("W-w-10", "H-h-10"))
        img_path = sc.watermark_image.path
        alpha = sc.watermark_opacity
        filter_complex = (
            f"[1:v]scale={sc.watermark_size}:-1,format=rgba,"
            f"colorchannelmixer=aa={alpha}[wm];"
            f"[0:v][wm]overlay={x}:{y}[outv]"
        )
        return [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-i",
            str(img_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[outv]",
            "-map",
            "0:a",
            "-c:v",
            "libx264",
            "-crf",
            str(self.crf),
            "-preset",
            self.preset,
            "-c:a",
            "copy",
            "-movflags",
            "faststart",
            str(self.output_path),
        ]
