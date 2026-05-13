from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

import ffmpeg

from reelforge.services.media.render_stages.base import RenderStage

if TYPE_CHECKING:
    from pathlib import Path

    from reelforge.clipping.models import ClipStyleConfig

logger = logging.getLogger("reelforge.media.render_stages")


@dataclass
class MusicMixStage(RenderStage):
    """Stage 10: Mix background music under the clip audio.

    Runs last so it covers the full assembled output including intro + outro.
    Uses amix filter to blend music with original audio. If the music track is
    shorter than the clip, it is looped via -stream_loop -1.
    Volume is specified in dB relative to original audio.
    """

    output_path: Path
    style_config: ClipStyleConfig | None
    video_duration_sec: float = 60.0

    @property
    def name(self) -> str:
        return "music_mix"

    @property
    def order(self) -> int:
        return 10

    def should_run(self) -> bool:
        if self.style_config is None or not self.style_config.music_enabled:
            return False
        return self.style_config.music_asset is not None

    def run(self, input_path: Path) -> Path:
        sc = self.style_config
        music_path = sc.music_asset.file.path
        music_duration = sc.music_asset.duration_sec or 0
        vol_db = sc.music_volume_db
        fade_in = sc.music_fade_in_sec
        fade_out = sc.music_fade_out_sec
        probe = ffmpeg.probe(str(input_path))
        dur = float(probe["format"]["duration"])

        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        music_filter = (
            f"volume={vol_db}dB,"
            f"afade=t=in:st=0:d={fade_in},"
            f"afade=t=out:st={max(0.0, dur - fade_out)}:d={fade_out}"
        )

        loop_flag = ["-stream_loop", "-1"] if music_duration < dur else []

        filter_complex = (
            f"[1:a]{music_filter}[music];"
            f"[0:a][music]amix=inputs=2:duration=first:dropout_transition=0[outa]"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            *loop_flag,
            "-i",
            str(music_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v",
            "-map",
            "[outa]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "faststart",
            str(self.output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            msg = f"MusicMixStage failed: {result.stderr}"
            raise RuntimeError(msg)
        logger.info(
            "MusicMixStage completed",
            extra={"output": str(self.output_path), "volume_db": vol_db},
        )
        return self.output_path
