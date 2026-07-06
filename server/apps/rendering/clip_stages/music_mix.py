"""MusicMixStage — mix background music and timed SFX into the clip."""

from __future__ import annotations

import logging
import subprocess  # noqa: S404
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, final, override

from server.apps.rendering.clip_stages.base import RenderStage

if TYPE_CHECKING:
    from server.apps.clips.models import ClipStyleConfig, ClipTimedSfx

logger = logging.getLogger('***REMOVED***.rendering.clip_stages')


@final
@dataclass
class MusicMixStage(RenderStage):
    """Mix background music and timed SFX one-shots with the clip audio."""

    output_path: Path
    style_config: ClipStyleConfig | None
    video_duration_sec: float
    timed_sfx: list[ClipTimedSfx] = field(default_factory=list)

    @property
    @override
    def name(self) -> str:
        """Short identifier for this stage."""
        return 'music_and_sfx_mix'

    @property
    @override
    def order(self) -> int:
        """Execution order (1-indexed)."""
        return 11

    @override
    def should_run(self) -> bool:
        music_active = (
            self.style_config is not None
            and self.style_config.music_enabled
            and self.style_config.music_asset is not None
        )
        return music_active or len(self.timed_sfx) > 0

    @override
    def run(self, input_path: Path) -> Path:
        """Mix background music and SFX into the clip."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        sc = self.style_config
        dur = self.video_duration_sec

        inputs = ['-i', str(input_path)]
        audio_labels: list[tuple[str, str]] = []
        tmp_paths: list[str] = []

        if sc is not None and sc.music_enabled and sc.music_asset is not None:
            music_bytes: bytes = sc.music_asset.file.read()
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
                music_path = tmp.name
            Path(music_path).write_bytes(music_bytes)
            tmp_paths.append(music_path)
            idx = len(tmp_paths)
            inputs += ['-i', music_path]
            gain = 10 ** (sc.music_volume_db / 20.0)
            fi, fo = sc.music_fade_in_sec, sc.music_fade_out_sec
            filt = (
                f'[{idx}:a]volume={gain:.4f},'
                f'afade=t=in:st=0:d={fi},'
                f'afade=t=out:st={max(0.0, dur - fo):.3f}:d={fo},'
                f'apad,atrim=duration={dur:.3f}[m{idx}]'
            )
            audio_labels.append((filt, f'[m{idx}]'))

        for sfx in self.timed_sfx:
            sfx_bytes: bytes = sfx.sfx_asset.file.read()
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
                sfx_path = tmp.name
            Path(sfx_path).write_bytes(sfx_bytes)
            tmp_paths.append(sfx_path)
            idx = len(tmp_paths)
            inputs += ['-i', sfx_path]
            gain = 10 ** (sfx.volume_db / 20.0)
            delay_ms = int(sfx.start_sec * 1000)
            filt = (
                f'[{idx}:a]volume={gain:.4f},'
                f'adelay={delay_ms}|{delay_ms}[s{idx}]'
            )
            audio_labels.append((filt, f'[s{idx}]'))

        filter_parts = [filt for filt, _ in audio_labels]
        refs = ''.join(label for _, label in audio_labels)
        n = 1 + len(audio_labels)
        filter_parts.append(
            f'[0:a]{refs}amix=inputs={n}:duration=first[aout]',
        )
        filter_complex = ';'.join(filter_parts)

        cmd = [
            'ffmpeg',
            '-y',
            *inputs,
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
        for p in tmp_paths:
            Path(p).unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(
                f'MusicMixStage ffmpeg failed: {result.stderr}',
            )
        return self.output_path
