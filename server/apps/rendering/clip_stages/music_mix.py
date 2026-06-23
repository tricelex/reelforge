"""MusicMixStage — stage 10: mix background music into the clip."""

from __future__ import annotations

import logging
import subprocess  # noqa: S404
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, final, override

from server.apps.rendering.clip_stages.base import RenderStage

if TYPE_CHECKING:
    from server.apps.clips.models import ClipStyleConfig

logger = logging.getLogger('***REMOVED***.rendering.clip_stages')


@final
@dataclass
class MusicMixStage(RenderStage):
    """Stage 10: Mix background music with the clip audio."""

    output_path: Path
    style_config: ClipStyleConfig | None
    video_duration_sec: float

    @property
    @override
    def name(self) -> str:
        """Short identifier for this stage."""
        return 'music_mix'

    @property
    @override
    def order(self) -> int:
        """Execution order (1-indexed)."""
        return 10

    @override
    def should_run(self) -> bool:
        """Return True if music is enabled and an asset is configured."""
        return (
            self.style_config is not None
            and self.style_config.music_enabled
            and self.style_config.music_asset is not None
        )

    @override
    def run(self, input_path: Path) -> Path:
        """Mix background music into the clip."""
        sc = self.style_config
        assert sc is not None  # noqa: S101
        assert sc.music_asset is not None  # noqa: S101

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        music_bytes: bytes = sc.music_asset.file.read()

        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
            music_path = tmp.name
        Path(music_path).write_bytes(music_bytes)

        vol_db = sc.music_volume_db
        gain = 10 ** (vol_db / 20.0)
        fi = sc.music_fade_in_sec
        fo = sc.music_fade_out_sec
        dur = self.video_duration_sec

        filter_complex = (
            f'[1:a]volume={gain:.4f},'
            f'afade=t=in:st=0:d={fi},'
            f'afade=t=out:st={max(0.0, dur - fo):.3f}:d={fo},'
            f'apad,atrim=duration={dur:.3f}[music];'
            f'[0:a][music]amix=inputs=2:duration=first[aout]'
        )
        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            str(input_path),
            '-i',
            music_path,
            '-filter_complex',
            filter_complex,
            '-map',
            '0:v',
            '-map',
            '[aout]',
            '-c:v',
            'copy',
            '-c:a',
            'aac',
            '-b:a',
            '192k',
            str(self.output_path),
        ]
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        Path(music_path).unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(
                f'MusicMixStage ffmpeg failed: {result.stderr}',
            )
        return self.output_path
