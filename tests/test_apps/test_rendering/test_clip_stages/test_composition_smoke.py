"""Real FFmpeg smoke tests for portrait composition layouts."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from server.apps.rendering.clip_stages.trim_crop import TrimAndCropStage

_OUT_W = 1080
_OUT_H = 1920
_GREEN_MIN = 100
_BG_R_MAX = 40
_BG_G_MAX = 50
_BG_B_MIN = 40


def _have_ffmpeg() -> bool:
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg is None:
        return False
    try:
        result = subprocess.run(  # noqa: S603
            [ffmpeg, '-version'],
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


pytestmark = pytest.mark.skipif(
    not _have_ffmpeg(),
    reason='ffmpeg not available',
)


def _make_landscape_source(path: Path) -> None:
    """Create a short deterministic 16:9 green clip."""
    ffmpeg = shutil.which('ffmpeg')
    assert ffmpeg is not None
    cmd = [
        ffmpeg,
        '-y',
        '-f',
        'lavfi',
        '-i',
        'color=c=0x00FF00:s=640x360:d=1',
        '-f',
        'lavfi',
        '-i',
        'sine=frequency=440:duration=1',
        '-c:v',
        'libx264',
        '-pix_fmt',
        'yuv420p',
        '-c:a',
        'aac',
        '-shortest',
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    assert result.returncode == 0, result.stderr


def _ffprobe(path: Path) -> dict[str, object]:
    ffprobe = shutil.which('ffprobe')
    assert ffprobe is not None
    cmd = [
        ffprobe,
        '-v',
        'quiet',
        '-print_format',
        'json',
        '-show_streams',
        '-show_format',
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _frame_pixel(path: Path, *, x: int, y: int) -> tuple[int, int, int]:
    """Extract one RGB pixel from the first frame via ffmpeg rawvideo."""
    ffmpeg = shutil.which('ffmpeg')
    assert ffmpeg is not None
    even_x = x - (x % 2)
    even_y = y - (y % 2)
    cmd = [
        ffmpeg,
        '-y',
        '-i',
        str(path),
        '-vf',
        f'crop=2:2:{even_x}:{even_y},format=rgb24',
        '-frames:v',
        '1',
        '-f',
        'rawvideo',
        '-pix_fmt',
        'rgb24',
        'pipe:1',
    ]
    result = subprocess.run(cmd, capture_output=True, check=False)  # noqa: S603
    assert result.returncode == 0, result.stderr.decode()
    assert len(result.stdout) >= 3
    return int(result.stdout[0]), int(result.stdout[1]), int(result.stdout[2])


class _Layout:
    render_mode = 'CENTER_CROP'
    fit_mode = 'CROP'
    foreground_treatment = 'CONTAIN'
    background_mode = 'SOLID'
    background_color = '#112233'
    blur_strength = 20
    manual_crop_x = None
    manual_crop_y = None
    manual_crop_w = None
    manual_crop_h = None
    has_spatial_regions = False
    stack_ratio = 0.6


def test_real_ffmpeg_contain_solid_portrait(tmp_path: Path) -> None:
    source = tmp_path / 'source.mp4'
    output = tmp_path / 'out.mp4'
    _make_landscape_source(source)

    layout = _Layout()
    stage = TrimAndCropStage(
        source_path=source,
        start_sec=0.0,
        end_sec=1.0,
        output_path=output,
        layout_config=layout,  # type: ignore[arg-type]
        width=_OUT_W,
        height=_OUT_H,
        crf=28,
        preset='ultrafast',
    )
    result = stage.run(source)
    assert result == output
    assert output.exists()

    probe = _ffprobe(output)
    streams = probe['streams']
    assert isinstance(streams, list)
    video = next(s for s in streams if s['codec_type'] == 'video')  # type: ignore[index]
    audio = next(s for s in streams if s['codec_type'] == 'audio')  # type: ignore[index]
    assert int(video['width']) == _OUT_W  # type: ignore[index]
    assert int(video['height']) == _OUT_H  # type: ignore[index]
    assert audio['codec_name'] == 'aac'  # type: ignore[index]

    top = _frame_pixel(output, x=540, y=40)
    assert top[0] < _BG_R_MAX and top[1] < _BG_G_MAX and top[2] > _BG_B_MIN

    mid = _frame_pixel(output, x=540, y=960)
    assert mid[1] > mid[0] and mid[1] > mid[2]


def test_real_ffmpeg_contain_blurred_portrait(tmp_path: Path) -> None:
    source = tmp_path / 'source.mp4'
    output = tmp_path / 'out.mp4'
    _make_landscape_source(source)

    layout = _Layout()
    layout.background_mode = 'BLURRED_SOURCE'
    layout.blur_strength = 10
    stage = TrimAndCropStage(
        source_path=source,
        start_sec=0.0,
        end_sec=1.0,
        output_path=output,
        layout_config=layout,  # type: ignore[arg-type]
        width=_OUT_W,
        height=_OUT_H,
        crf=28,
        preset='ultrafast',
    )
    stage.run(source)
    probe = _ffprobe(output)
    streams = probe['streams']
    assert isinstance(streams, list)
    video = next(s for s in streams if s['codec_type'] == 'video')  # type: ignore[index]
    assert int(video['width']) == _OUT_W  # type: ignore[index]
    assert int(video['height']) == _OUT_H  # type: ignore[index]
    mid = _frame_pixel(output, x=540, y=960)
    assert mid[1] > _GREEN_MIN
