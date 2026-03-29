from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from ***REMOVED***.services.media.render_stages.base import RenderStage

logger = logging.getLogger("***REMOVED***.media.render_stages")


@dataclass
class TimedOverlayStage(RenderStage):
    """Stage 7: Composite all timed text/image overlays in a single ffmpeg pass."""

    output_path: Path
    timed_overlays: list[Any] = field(default_factory=list)  # list[ClipTimedOverlay]

    @property
    def name(self) -> str:
        return "timed_overlays"

    @property
    def order(self) -> int:
        return 7

    def should_run(self) -> bool:
        return bool(self.timed_overlays)

    def run(self, input_path: Path) -> Path:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        text_overlays = [o for o in self.timed_overlays if o.overlay_type == "TEXT"]
        image_overlays = [o for o in self.timed_overlays if o.overlay_type == "IMAGE"]

        if image_overlays:
            cmd = self._build_mixed_command(input_path, text_overlays, image_overlays)
        else:
            cmd = self._build_text_only_command(input_path, text_overlays)

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"TimedOverlayStage failed: {result.stderr}")
        logger.info("TimedOverlayStage completed", extra={"count": len(self.timed_overlays)})
        return self.output_path

    def _build_text_only_command(self, input_path: Path, overlays: list[Any]) -> list[str]:
        filters = []
        for o in overlays:
            text = o.text.replace("'", "\\'").replace(":", "\\:")
            color = o.font_color.lstrip("#")
            filters.append(
                f"drawtext=text='{text}'"
                f":fontsize={o.font_size}"
                f":fontcolor=0x{color}@{o.opacity}"
                f":x={o.position_x - o.font_size // 2}"
                f":y={o.position_y - o.font_size // 2}"
                f":enable='between(t,{o.start_sec},{o.end_sec})'"
            )
        vf = ",".join(filters)
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
            "18",
            "-preset",
            "slow",
            "-c:a",
            "copy",
            "-movflags",
            "faststart",
            str(self.output_path),
        ]

    def _build_mixed_command(
        self,
        input_path: Path,
        text_overlays: list[Any],
        image_overlays: list[Any],
    ) -> list[str]:
        inputs = ["-i", str(input_path)]
        for o in image_overlays:
            inputs += ["-i", str(o.image.path)]

        fc_parts = []
        prev = "0:v"
        for idx, o in enumerate(image_overlays):
            img_idx = idx + 1
            tag_out = f"ov{idx}"
            fc_parts.append(
                f"[{prev}][{img_idx}:v]overlay={o.position_x}:{o.position_y}"
                f":enable='between(t,{o.start_sec},{o.end_sec})'[{tag_out}]"
            )
            prev = tag_out

        text_filters = []
        for o in text_overlays:
            text = o.text.replace("'", "\\'").replace(":", "\\:")
            color = o.font_color.lstrip("#")
            text_filters.append(
                f"drawtext=text='{text}'"
                f":fontsize={o.font_size}"
                f":fontcolor=0x{color}@{o.opacity}"
                f":x={o.position_x}:y={o.position_y}"
                f":enable='between(t,{o.start_sec},{o.end_sec})'"
            )
        if text_filters:
            fc_parts.append(f"[{prev}]{','.join(text_filters)}[outv]")
            final_map = "[outv]"
        else:
            final_map = f"[{prev}]"

        return [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(fc_parts),
            "-map",
            final_map,
            "-map",
            "0:a",
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
