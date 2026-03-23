from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

import ffmpeg

logger = logging.getLogger("reelforge.media.clip_renderer")


@dataclass
class ClipRenderConfig:
    source_path: Path
    output_path: Path
    start_sec: float
    end_sec: float
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = "slow"
    audio_bitrate: str = "192k"
    include_captions: bool = True
    include_title_card: bool = True
    include_branding: bool = True
    hook_text: str = ""
    transcript_json: dict[str, Any] = field(default_factory=dict)
    intro_path: Path | None = None
    outro_path: Path | None = None


class ClipRenderer:
    def __init__(self, config: ClipRenderConfig) -> None:
        self.config = config

    def render(self) -> Path:
        logger.info(
            "Starting clip render",
            extra={
                "source": str(self.config.source_path),
                "output": str(self.config.output_path),
                "start_sec": self.config.start_sec,
                "end_sec": self.config.end_sec,
            },
        )

        # Validate source exists via ffprobe
        probe = ffmpeg.probe(str(self.config.source_path))
        if not probe:
            msg = f"Cannot probe source file: {self.config.source_path}"
            raise ValueError(msg)

        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)

        start_time = time.perf_counter()
        cmd = self._build_ffmpeg_command()
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr}")

        elapsed = time.perf_counter() - start_time
        logger.info(
            "Clip render completed",
            extra={
                "output": str(self.config.output_path),
                "render_duration_sec": elapsed,
            },
        )
        return self.config.output_path

    def _build_ffmpeg_command(self) -> list[str]:
        c = self.config
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(c.start_sec),
            "-to", str(c.end_sec),
            "-i", str(c.source_path),
            # Crop to 9:16 center
            "-vf", f"crop=ih*9/16:ih,scale={c.width}:{c.height},fps={c.fps}",
            # Video codec
            "-c:v", "libx264",
            "-crf", str(c.crf),
            "-preset", c.preset,
            # Audio
            "-c:a", "aac",
            "-b:a", c.audio_bitrate,
            # Streaming optimized
            "-movflags", "faststart",
            str(c.output_path),
        ]
        return cmd

    def get_output_duration(self) -> float:
        if not self.config.output_path.exists():
            return 0.0
        probe = ffmpeg.probe(str(self.config.output_path))
        return float(probe["format"]["duration"])
