from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import ffmpeg

from reelforge.services.media.render_stages.base import RenderStage

if TYPE_CHECKING:
    from reelforge.clipping.models import ClipStyleConfig

logger = logging.getLogger("reelforge.media.render_stages")

# Maps our TransitionStyle choices to ffmpeg xfade transition names
_XFADE_MAP = {
    "CROSSFADE": "fade",
    "FADE_BLACK": "fadeblack",
    "WIPE_LEFT": "wipeleft",
    "WIPE_RIGHT": "wiperight",
}


def _get_duration(path: Path) -> float:
    """Return video duration in seconds via ffprobe."""
    probe = ffmpeg.probe(str(path))
    return float(probe["format"]["duration"])


def _concat_hard_cut(
    clip_a: Path,
    clip_b: Path,
    output: Path,
    crf: int,
    preset: str,
    audio_bitrate: str,
) -> None:
    """Concatenate two videos with a hard cut using ffmpeg filter_complex concat."""
    filter_complex = "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[outv][outa]"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_a),
        "-i", str(clip_b),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-movflags", "faststart",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        msg = f"concat failed: {result.stderr}"
        raise RuntimeError(msg)


def _concat_xfade(
    clip_a: Path,
    clip_b: Path,
    output: Path,
    xfade_name: str,
    duration: float,
    crf: int,
    preset: str,
    audio_bitrate: str,
) -> None:
    """Concatenate two videos with an xfade transition."""
    a_duration = _get_duration(clip_a)
    offset = max(0.0, a_duration - duration)
    filter_complex = (
        f"[0:v][1:v]xfade=transition={xfade_name}:duration={duration}:offset={offset}[outv];"
        f"[0:a][1:a]acrossfade=d={duration}[outa]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_a),
        "-i", str(clip_b),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-movflags", "faststart",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        msg = f"xfade concat failed: {result.stderr}"
        raise RuntimeError(msg)


@dataclass
class IntroConcatStage(RenderStage):
    """Stage 2: Prepend the channel intro clip before the main content."""

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
        return "intro_concat"

    @property
    def order(self) -> int:
        return 2

    def should_run(self) -> bool:
        return self.style_config is not None and self.style_config.intro_asset is not None

    def run(self, input_path: Path) -> Path:
        sc = self.style_config
        intro_path = Path(sc.intro_asset.file.path)
        transition = sc.intro_transition
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        if transition == "NONE":
            _concat_hard_cut(intro_path, input_path, self.output_path, self.crf, self.preset, self.audio_bitrate)
        else:
            xfade_name = _XFADE_MAP.get(transition, "fade")
            _concat_xfade(
                intro_path, input_path, self.output_path,
                xfade_name, sc.transition_duration_sec,
                self.crf, self.preset, self.audio_bitrate,
            )
        logger.info("IntroConcatStage completed", extra={"output": str(self.output_path)})
        return self.output_path


@dataclass
class OutroConcatStage(RenderStage):
    """Stage 9: Append the channel outro clip after the main content."""

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
        return "outro_concat"

    @property
    def order(self) -> int:
        return 9

    def should_run(self) -> bool:
        return self.style_config is not None and self.style_config.outro_asset is not None

    def run(self, input_path: Path) -> Path:
        sc = self.style_config
        outro_path = Path(sc.outro_asset.file.path)
        transition = sc.outro_transition
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        if transition == "NONE":
            _concat_hard_cut(input_path, outro_path, self.output_path, self.crf, self.preset, self.audio_bitrate)
        else:
            xfade_name = _XFADE_MAP.get(transition, "fade")
            _concat_xfade(
                input_path, outro_path, self.output_path,
                xfade_name, sc.transition_duration_sec,
                self.crf, self.preset, self.audio_bitrate,
            )
        logger.info("OutroConcatStage completed", extra={"output": str(self.output_path)})
        return self.output_path
