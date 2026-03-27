from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import ffmpeg

from ***REMOVED***.services.media.speaker_detection import SpeakerCropResult
from ***REMOVED***.services.media.speaker_detection import SpeakerDetectionService

if TYPE_CHECKING:
    from ***REMOVED***.clipping.models import ClipLayoutConfig

logger = logging.getLogger("***REMOVED***.media.clip_renderer")


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
    layout_config: ClipLayoutConfig | None = None


class ClipRenderer:
    def __init__(self, config: ClipRenderConfig) -> None:
        self.config = config
        self.last_speaker_crop_result: SpeakerCropResult | None = None

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
        from ***REMOVED***.clipping.models import ClipLayoutConfig

        lc = self.config.layout_config
        render_mode = lc.render_mode if lc else ClipLayoutConfig.RenderMode.CENTER_CROP

        if render_mode == ClipLayoutConfig.RenderMode.SPATIAL_STACK:
            return self._build_spatial_stack_command()
        if render_mode == ClipLayoutConfig.RenderMode.SMART_CROP:
            return self._build_smart_crop_command()
        return self._build_center_crop_command()

    def _build_center_crop_command(self) -> list[str]:
        c = self.config
        return [
            "ffmpeg",
            "-y",
            "-ss", str(c.start_sec),
            "-to", str(c.end_sec),
            "-i", str(c.source_path),
            "-vf", f"crop=ih*9/16:ih,scale={c.width}:{c.height},fps={c.fps}",
            "-c:v", "libx264",
            "-crf", str(c.crf),
            "-preset", c.preset,
            "-c:a", "aac",
            "-b:a", c.audio_bitrate,
            "-movflags", "faststart",
            str(c.output_path),
        ]

    def _build_smart_crop_command(self) -> list[str]:
        c = self.config
        lc = c.layout_config

        # Determine crop_x: manual override takes priority over auto-detection
        if lc is not None and lc.has_manual_smart_crop:
            crop_x = lc.manual_crop_x
            crop_w = lc.manual_crop_w
            crop_h = lc.manual_crop_h
        else:
            service = SpeakerDetectionService()
            result = service.detect(c.source_path, c.start_sec, c.end_sec)
            self.last_speaker_crop_result = result
            crop_x = result.crop_x
            crop_w = result.crop_w
            crop_h = result.crop_h

        vf = f"crop={crop_w}:{crop_h}:{crop_x}:0,scale={c.width}:{c.height},fps={c.fps}"
        return [
            "ffmpeg",
            "-y",
            "-ss", str(c.start_sec),
            "-to", str(c.end_sec),
            "-i", str(c.source_path),
            "-vf", vf,
            "-c:v", "libx264",
            "-crf", str(c.crf),
            "-preset", c.preset,
            "-c:a", "aac",
            "-b:a", c.audio_bitrate,
            "-movflags", "faststart",
            str(c.output_path),
        ]

    def _build_spatial_stack_command(self) -> list[str]:
        """Build an FFmpeg filter_complex command that stacks two spatial regions vertically.

        Region A (top) and Region B (bottom) are cropped from the same source frame
        and stacked into a 9:16 output. The stack_ratio controls how much of the output
        height goes to region A.
        """
        c = self.config
        lc = c.layout_config

        if lc is None or not lc.has_spatial_regions:
            # Fall back to center crop if regions are not configured
            logger.warning(
                "SPATIAL_STACK requested but regions not configured — falling back to center crop",
                extra={"layout_config_id": str(lc.id) if lc else None},
            )
            return self._build_center_crop_command()

        out_w = c.width   # 1080
        out_h = c.height  # 1920
        a_out_h = int(out_h * lc.stack_ratio)
        b_out_h = out_h - a_out_h

        filter_complex = (
            f"[0:v]trim=start={c.start_sec}:end={c.end_sec},setpts=PTS-STARTPTS,"
            f"crop={lc.region_a_w}:{lc.region_a_h}:{lc.region_a_x}:{lc.region_a_y},"
            f"scale={out_w}:{a_out_h}[top];"
            f"[0:v]trim=start={c.start_sec}:end={c.end_sec},setpts=PTS-STARTPTS,"
            f"crop={lc.region_b_w}:{lc.region_b_h}:{lc.region_b_x}:{lc.region_b_y},"
            f"scale={out_w}:{b_out_h}[bottom];"
            f"[top][bottom]vstack=inputs=2[out]"
        )

        return [
            "ffmpeg",
            "-y",
            "-i", str(c.source_path),
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a",
            "-ss", str(c.start_sec),
            "-to", str(c.end_sec),
            "-c:v", "libx264",
            "-crf", str(c.crf),
            "-preset", c.preset,
            "-c:a", "aac",
            "-b:a", c.audio_bitrate,
            "-movflags", "faststart",
            str(c.output_path),
        ]

    def get_output_duration(self) -> float:
        if not self.config.output_path.exists():
            return 0.0
        probe = ffmpeg.probe(str(self.config.output_path))
        return float(probe["format"]["duration"])
