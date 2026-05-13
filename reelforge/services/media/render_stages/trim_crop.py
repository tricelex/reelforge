from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

import ffmpeg

from reelforge.services.media.render_stages.base import RenderStage
from reelforge.services.media.speaker_detection import SpeakerCropResult
from reelforge.services.media.speaker_detection import SpeakerDetectionService

if TYPE_CHECKING:
    from pathlib import Path

    from reelforge.clipping.models import ClipLayoutConfig

logger = logging.getLogger("reelforge.media.render_stages")


@dataclass
class TrimAndCropStage(RenderStage):
    """Stage 1: Trim the source video to clip boundaries and crop to 9:16.

    Absorbs the three crop modes from the legacy ClipRenderer:
    CENTER_CROP, SMART_CROP (with speaker detection), and SPATIAL_STACK.
    """

    source_path: Path
    start_sec: float
    end_sec: float
    output_path: Path
    layout_config: ClipLayoutConfig | None
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = "slow"
    audio_bitrate: str = "192k"
    last_speaker_crop_result: SpeakerCropResult | None = field(default=None, init=False)

    @property
    def name(self) -> str:
        return "trim_and_crop"

    @property
    def order(self) -> int:
        return 1

    def run(self, input_path: Path) -> Path:
        probe = ffmpeg.probe(str(input_path))
        if not probe:
            msg = f"Cannot probe source: {input_path}"
            raise ValueError(msg)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = self._build_command(input_path)
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            msg = f"TrimAndCropStage ffmpeg failed: {result.stderr}"
            raise RuntimeError(msg)
        logger.info(
            "TrimAndCropStage completed",
            extra={"output": str(self.output_path)},
        )
        return self.output_path

    def _build_command(self, input_path: Path) -> list[str]:
        from reelforge.clipping.models import ClipLayoutConfig as LC

        render_mode = self.layout_config.render_mode if self.layout_config else LC.RenderMode.CENTER_CROP

        if render_mode == LC.RenderMode.SPATIAL_STACK:
            return self._build_spatial_stack_command(input_path)
        if render_mode == LC.RenderMode.SMART_CROP:
            return self._build_smart_crop_command(input_path)
        return self._build_center_crop_command(input_path)

    def _build_center_crop_command(self, input_path: Path) -> list[str]:
        return [
            "ffmpeg", "-y",
            "-ss", str(self.start_sec),
            "-to", str(self.end_sec),
            "-i", str(input_path),
            "-vf", f"crop=ih*9/16:ih,scale={self.width}:{self.height},fps={self.fps}",
            "-c:v", "libx264",
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-c:a", "aac",
            "-b:a", self.audio_bitrate,
            "-movflags", "faststart",
            str(self.output_path),
        ]

    def _build_smart_crop_command(self, input_path: Path) -> list[str]:
        lc = self.layout_config
        service = SpeakerDetectionService()
        result = service.detect(
            video_path=input_path,
            start_sec=self.start_sec,
            end_sec=self.end_sec,
            manual_crop_x=lc.manual_crop_x if lc is not None else None,
            manual_crop_y=lc.manual_crop_y if lc is not None else None,
            manual_crop_w=lc.manual_crop_w if lc is not None else None,
            manual_crop_h=lc.manual_crop_h if lc is not None else None,
        )
        self.last_speaker_crop_result = result
        crop_x = result.crop_x
        crop_w = result.crop_w
        crop_h = result.crop_h
        vf = f"crop={crop_w}:{crop_h}:{crop_x}:0,scale={self.width}:{self.height},fps={self.fps}"
        return [
            "ffmpeg", "-y",
            "-ss", str(self.start_sec),
            "-to", str(self.end_sec),
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264",
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-c:a", "aac",
            "-b:a", self.audio_bitrate,
            "-movflags", "faststart",
            str(self.output_path),
        ]

    def _build_spatial_stack_command(self, input_path: Path) -> list[str]:
        lc = self.layout_config
        if lc is None or not lc.has_spatial_regions:
            logger.warning("SPATIAL_STACK has no regions — falling back to center crop")
            return self._build_center_crop_command(input_path)

        out_w = self.width
        out_h = self.height
        a_out_h = int(out_h * lc.stack_ratio)
        b_out_h = out_h - a_out_h

        filter_complex = (
            f"[0:v]trim=start={self.start_sec}:end={self.end_sec},setpts=PTS-STARTPTS,"
            f"crop={lc.region_a_w}:{lc.region_a_h}:{lc.region_a_x}:{lc.region_a_y},"
            f"scale={out_w}:{a_out_h}[top];"
            f"[0:v]trim=start={self.start_sec}:end={self.end_sec},setpts=PTS-STARTPTS,"
            f"crop={lc.region_b_w}:{lc.region_b_h}:{lc.region_b_x}:{lc.region_b_y},"
            f"scale={out_w}:{b_out_h}[bottom];"
            f"[top][bottom]vstack=inputs=2[out]"
        )
        return [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a",
            "-c:v", "libx264",
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-c:a", "aac",
            "-b:a", self.audio_bitrate,
            "-movflags", "faststart",
            str(self.output_path),
        ]
