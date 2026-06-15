"""IntroConcatStage and OutroConcatStage — prepend/append intro/outro clips."""

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

logger = logging.getLogger('reelforge.rendering.clip_stages')


@final
@dataclass
class IntroConcatStage(RenderStage):
    """Stage 2: Prepend intro clip if configured."""

    output_path: Path
    style_config: ClipStyleConfig | None
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = 'slow'
    audio_bitrate: str = '192k'

    @property
    @override
    def name(self) -> str:
        """Short identifier for this stage."""
        return 'intro_concat'

    @property
    @override
    def order(self) -> int:
        """Execution order (1-indexed)."""
        return 2

    @override
    def should_run(self) -> bool:
        """Return True if intro asset is configured."""
        return (
            self.style_config is not None
            and self.style_config.intro_asset is not None
        )

    @override
    def run(self, input_path: Path) -> Path:
        """Concatenate intro asset before the main clip."""
        sc = self.style_config
        assert sc is not None  # noqa: S101
        assert sc.intro_asset is not None  # noqa: S101

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        intro_bytes: bytes = sc.intro_asset.file.read()

        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            intro_path = tmp.name
        Path(intro_path).write_bytes(intro_bytes)

        # Scale intro to target resolution
        scaled_intro = intro_path + '_scaled.mp4'
        scale_cmd = [
            'ffmpeg', '-y', '-i', intro_path,
            '-vf',
            f'scale={self.width}:{self.height},fps={self.fps}',
            '-c:v', 'libx264', '-crf', str(self.crf), '-preset', self.preset,
            '-c:a', 'aac', '-b:a', self.audio_bitrate,
            scaled_intro,
        ]
        self._run_ffmpeg(scale_cmd, 'IntroConcatStage scale')

        # Concat intro + main
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.txt', delete=False, encoding='utf-8',
        ) as f:
            f.write(f"file '{scaled_intro}'\n")
            f.write(f"file '{input_path}'\n")
            list_path = f.name

        concat_cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', list_path,
            '-c', 'copy', str(self.output_path),
        ]
        self._run_ffmpeg(concat_cmd, 'IntroConcatStage concat')

        Path(intro_path).unlink(missing_ok=True)
        Path(scaled_intro).unlink(missing_ok=True)
        Path(list_path).unlink(missing_ok=True)
        return self.output_path

    def _run_ffmpeg(self, cmd: list[str], label: str) -> None:
        result = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f'{label} ffmpeg failed: {result.stderr}',
            )


@final
@dataclass
class OutroConcatStage(RenderStage):
    """Stage 9: Append outro clip if configured."""

    output_path: Path
    style_config: ClipStyleConfig | None
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = 'slow'
    audio_bitrate: str = '192k'

    @property
    @override
    def name(self) -> str:
        """Short identifier for this stage."""
        return 'outro_concat'

    @property
    @override
    def order(self) -> int:
        """Execution order (1-indexed)."""
        return 9

    @override
    def should_run(self) -> bool:
        """Return True if outro asset is configured."""
        return (
            self.style_config is not None
            and self.style_config.outro_asset is not None
        )

    @override
    def run(self, input_path: Path) -> Path:
        """Concatenate outro asset after the main clip."""
        sc = self.style_config
        assert sc is not None  # noqa: S101
        assert sc.outro_asset is not None  # noqa: S101

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        outro_bytes: bytes = sc.outro_asset.file.read()

        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            outro_path = tmp.name
        Path(outro_path).write_bytes(outro_bytes)

        scaled_outro = outro_path + '_scaled.mp4'
        scale_cmd = [
            'ffmpeg', '-y', '-i', outro_path,
            '-vf',
            f'scale={self.width}:{self.height},fps={self.fps}',
            '-c:v', 'libx264', '-crf', str(self.crf), '-preset', self.preset,
            '-c:a', 'aac', '-b:a', self.audio_bitrate,
            scaled_outro,
        ]
        result = subprocess.run(  # noqa: S603
            scale_cmd, capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f'OutroConcatStage ffmpeg scale failed: {result.stderr}',
            )

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.txt', delete=False, encoding='utf-8',
        ) as f:
            f.write(f"file '{input_path}'\n")
            f.write(f"file '{scaled_outro}'\n")
            list_path = f.name

        concat_cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', list_path,
            '-c', 'copy', str(self.output_path),
        ]
        r2 = subprocess.run(  # noqa: S603
            concat_cmd, capture_output=True, text=True, check=False,
        )
        if r2.returncode != 0:
            raise RuntimeError(
                f'OutroConcatStage ffmpeg concat failed: {r2.stderr}',
            )

        Path(outro_path).unlink(missing_ok=True)
        Path(scaled_outro).unlink(missing_ok=True)
        Path(list_path).unlink(missing_ok=True)
        return self.output_path
