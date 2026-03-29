from __future__ import annotations

import logging
import subprocess
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
        return text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")

    def _drawtext_filter(self, sc, y_expr: str, enable_expr: str) -> str:
        text = self._escape_text(self.hook_text)
        color = sc.hook_color.lstrip("#")
        bg = sc.hook_bg_color.lstrip("#")
        return (
            f"drawtext=text='{text}'"
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
            gen_cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", f"color=black:size={self.width}x{self.height}:rate={self.fps}",
                "-i", "anullsrc",
                "-vf", (
                    f"drawtext=text='{self._escape_text(self.hook_text)}'"
                    f":fontsize={sc.hook_size}:fontcolor=white"
                    f":x=(w-text_w)/2:y=(h-text_h)/2"
                ),
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
