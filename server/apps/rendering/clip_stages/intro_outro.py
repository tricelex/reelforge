"""IntroConcatStage and OutroConcatStage — prepend/append intro/outro clips."""

from __future__ import annotations

import logging
import subprocess  # noqa: S404
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, final, override

from server.apps.rendering.clip_stages.base import RenderStage
from server.apps.rendering.clip_stages.probe import sync_ffprobe_duration

if TYPE_CHECKING:
    from server.apps.clips.models import ClipStyleConfig

logger = logging.getLogger('reelforge.rendering.clip_stages')

_XFADE_TRANSITIONS: dict[str, str] = {
    'CROSSFADE': 'fade',
    'FADE_BLACK': 'fadeblack',
    'FADE_WHITE': 'fadewhite',
    'SLIDE_LEFT': 'slideleft',
    'SLIDE_RIGHT': 'slideright',
    'SLIDE_UP': 'slideup',
    'SLIDE_DOWN': 'slidedown',
    'WIPE_LEFT': 'wipeleft',
    'WIPE_RIGHT': 'wiperight',
    'ZOOM_IN': 'zoomin',
}

_MAX_TRANSITION_FRACTION = 0.9


def _run_ffmpeg(cmd: list[str], label: str) -> None:
    result = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f'{label} ffmpeg failed: {result.stderr}')


def _scale_asset(
    asset_bytes: bytes,
    *,
    width: int,
    height: int,
    fps: int,
    crf: int,
    preset: str,
    audio_bitrate: str,
    label: str,
) -> str:
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
        src_path = tmp.name
    Path(src_path).write_bytes(asset_bytes)

    scaled_path = src_path + '_scaled.mp4'
    _run_ffmpeg(
        [
            'ffmpeg',
            '-y',
            '-i',
            src_path,
            '-vf',
            f'scale={width}:{height},fps={fps}',
            '-c:v',
            'libx264',
            '-crf',
            str(crf),
            '-preset',
            preset,
            '-c:a',
            'aac',
            '-b:a',
            audio_bitrate,
            scaled_path,
        ],
        f'{label} scale',
    )
    Path(src_path).unlink(missing_ok=True)
    return scaled_path


def _fast_concat(first: str, second: str, output_path: Path, label: str) -> None:
    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.txt',
        delete=False,
        encoding='utf-8',
    ) as f:
        f.write(f"file '{first}'\n")
        f.write(f"file '{second}'\n")
        list_path = f.name
    _run_ffmpeg(
        [
            'ffmpeg',
            '-y',
            '-f',
            'concat',
            '-safe',
            '0',
            '-i',
            list_path,
            '-c',
            'copy',
            str(output_path),
        ],
        f'{label} concat',
    )
    Path(list_path).unlink(missing_ok=True)


def _xfade_transition_cmd(
    *,
    first_path: str,
    second_path: str,
    xfade_name: str,
    duration: float,
    offset: float,
    output_path: Path,
    crf: int,
    preset: str,
    fps: int,
    audio_bitrate: str,
) -> list[str]:
    filter_complex = (
        f'[0:v][1:v]xfade=transition={xfade_name}:duration={duration:.3f}'
        f':offset={offset:.3f}[v];'
        f'[0:a][1:a]acrossfade=d={duration:.3f}[a]'
    )
    return [
        'ffmpeg',
        '-y',
        '-i',
        first_path,
        '-i',
        second_path,
        '-filter_complex',
        filter_complex,
        '-map',
        '[v]',
        '-map',
        '[a]',
        '-c:v',
        'libx264',
        '-crf',
        str(crf),
        '-preset',
        preset,
        '-pix_fmt',
        'yuv420p',
        '-r',
        str(fps),
        '-c:a',
        'aac',
        '-b:a',
        audio_bitrate,
        str(output_path),
    ]


def _custom_asset_transition_cmd(
    *,
    first_path: str,
    second_path: str,
    transition_asset_path: str,
    duration: float,
    output_path: Path,
    crf: int,
    preset: str,
    fps: int,
    audio_bitrate: str,
) -> list[str]:
    filter_complex = (
        '[0:v][1:v]concat=n=2:v=1:a=0[base];'
        '[base][2:v]blend=all_mode=screen:all_opacity=1[v]'
    )
    return [
        'ffmpeg',
        '-y',
        '-i',
        first_path,
        '-i',
        second_path,
        '-i',
        transition_asset_path,
        '-filter_complex',
        filter_complex,
        '-map',
        '[v]',
        '-map',
        '0:a',
        '-c:v',
        'libx264',
        '-crf',
        str(crf),
        '-preset',
        preset,
        '-pix_fmt',
        'yuv420p',
        '-r',
        str(fps),
        '-c:a',
        'aac',
        '-b:a',
        audio_bitrate,
        str(output_path),
    ]


def _clamped_transition_duration(
    configured: float,
    first_dur: float,
    second_dur: float,
) -> float:
    max_allowed = min(first_dur, second_dur) * _MAX_TRANSITION_FRACTION
    return min(configured, max_allowed)


def _apply_boundary(
    *,
    transition: str,
    duration_sec: float,
    first_path: str,
    second_path: str,
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    crf: int,
    preset: str,
    audio_bitrate: str,
    label: str,
    transition_asset_bytes: bytes | None = None,
) -> None:
    if transition == 'CUSTOM_ASSET' and transition_asset_bytes is not None:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            asset_path = tmp.name
        Path(asset_path).write_bytes(transition_asset_bytes)
        cmd = _custom_asset_transition_cmd(
            first_path=first_path,
            second_path=second_path,
            transition_asset_path=asset_path,
            duration=duration_sec,
            output_path=output_path,
            crf=crf,
            preset=preset,
            fps=fps,
            audio_bitrate=audio_bitrate,
        )
        _run_ffmpeg(cmd, f'{label} custom transition')
        Path(asset_path).unlink(missing_ok=True)
        return
    if transition == 'NONE' or transition not in _XFADE_TRANSITIONS:
        _fast_concat(first_path, second_path, output_path, label)
        return
    first_dur = sync_ffprobe_duration(first_path)
    second_dur = sync_ffprobe_duration(second_path)
    duration = _clamped_transition_duration(duration_sec, first_dur, second_dur)
    offset = max(0.0, first_dur - duration)
    cmd = _xfade_transition_cmd(
        first_path=first_path,
        second_path=second_path,
        xfade_name=_XFADE_TRANSITIONS[transition],
        duration=duration,
        offset=offset,
        output_path=output_path,
        crf=crf,
        preset=preset,
        fps=fps,
        audio_bitrate=audio_bitrate,
    )
    _run_ffmpeg(cmd, f'{label} xfade')


@final
@dataclass
class IntroConcatStage(RenderStage):
    """Stage: prepend intro clip, applying a transition if configured."""

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
        return 'intro_concat'

    @property
    @override
    def order(self) -> int:
        return 3

    @override
    def should_run(self) -> bool:
        return (
            self.style_config is not None
            and self.style_config.intro_asset is not None
        )

    @override
    def run(self, input_path: Path) -> Path:
        sc = self.style_config
        assert sc is not None  # noqa: S101
        assert sc.intro_asset is not None  # noqa: S101

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        intro_bytes: bytes = sc.intro_asset.file.read()
        scaled_intro = _scale_asset(
            intro_bytes,
            width=self.width,
            height=self.height,
            fps=self.fps,
            crf=self.crf,
            preset=self.preset,
            audio_bitrate=self.audio_bitrate,
            label='IntroConcatStage',
        )
        transition_asset_bytes = (
            sc.intro_transition_asset.file.read()
            if sc.intro_transition_asset
            else None
        )
        _apply_boundary(
            transition=sc.intro_transition,
            duration_sec=sc.intro_transition_duration_sec,
            first_path=scaled_intro,
            second_path=str(input_path),
            output_path=self.output_path,
            width=self.width,
            height=self.height,
            fps=self.fps,
            crf=self.crf,
            preset=self.preset,
            audio_bitrate=self.audio_bitrate,
            label='IntroConcatStage',
            transition_asset_bytes=transition_asset_bytes,
        )
        Path(scaled_intro).unlink(missing_ok=True)
        return self.output_path


@final
@dataclass
class OutroConcatStage(RenderStage):
    """Stage: append outro clip, applying a transition if configured."""

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
        return 'outro_concat'

    @property
    @override
    def order(self) -> int:
        return 10

    @override
    def should_run(self) -> bool:
        return (
            self.style_config is not None
            and self.style_config.outro_asset is not None
        )

    @override
    def run(self, input_path: Path) -> Path:
        sc = self.style_config
        assert sc is not None  # noqa: S101
        assert sc.outro_asset is not None  # noqa: S101

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        outro_bytes: bytes = sc.outro_asset.file.read()
        scaled_outro = _scale_asset(
            outro_bytes,
            width=self.width,
            height=self.height,
            fps=self.fps,
            crf=self.crf,
            preset=self.preset,
            audio_bitrate=self.audio_bitrate,
            label='OutroConcatStage',
        )
        transition_asset_bytes = (
            sc.outro_transition_asset.file.read()
            if sc.outro_transition_asset
            else None
        )
        _apply_boundary(
            transition=sc.outro_transition,
            duration_sec=sc.outro_transition_duration_sec,
            first_path=str(input_path),
            second_path=scaled_outro,
            output_path=self.output_path,
            width=self.width,
            height=self.height,
            fps=self.fps,
            crf=self.crf,
            preset=self.preset,
            audio_bitrate=self.audio_bitrate,
            label='OutroConcatStage',
            transition_asset_bytes=transition_asset_bytes,
        )
        Path(scaled_outro).unlink(missing_ok=True)
        return self.output_path
