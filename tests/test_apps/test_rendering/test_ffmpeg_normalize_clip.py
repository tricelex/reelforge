"""Tests for normalizing sourced clips to a scene duration."""

import asyncio
from pathlib import Path

from server.apps.rendering.ffmpeg import async_ffprobe, normalize_clip


def _synthetic_clip(tmp_path: Path, seconds: float) -> bytes:
    """Render a short test clip at a non-target resolution."""
    out = tmp_path / f'src_{seconds}.mp4'

    async def _render() -> None:
        # Subprocess creation and wait() must share one event loop — Python
        # 3.13's asyncio subprocess transport cannot be awaited from a loop
        # other than the one that spawned it.
        proc = await asyncio.create_subprocess_exec(
            'ffmpeg',
            '-y',
            '-f',
            'lavfi',
            '-i',
            f'testsrc=size=640x480:rate=25:duration={seconds}',
            '-c:v',
            'libx264',
            '-pix_fmt',
            'yuv420p',
            str(out),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    asyncio.run(_render())
    return out.read_bytes()


def test_longer_clip_is_trimmed_from_the_start(tmp_path: Path) -> None:
    """A clip longer than the scene is trimmed, not looped."""
    source = _synthetic_clip(tmp_path, seconds=10.0)
    result, method = asyncio.run(normalize_clip(source, duration_s=4.0))
    assert method == 'clip_trim'
    out = tmp_path / 'trim.mp4'
    out.write_bytes(result)
    probe = asyncio.run(async_ffprobe(str(out)))
    assert 3.5 <= float(probe['format']['duration']) <= 4.5


def test_shorter_clip_is_looped_to_fill(tmp_path: Path) -> None:
    """A clip shorter than the scene loops to reach the target length."""
    source = _synthetic_clip(tmp_path, seconds=2.0)
    result, method = asyncio.run(normalize_clip(source, duration_s=6.0))
    assert method == 'clip_loop'
    out = tmp_path / 'loop.mp4'
    out.write_bytes(result)
    probe = asyncio.run(async_ffprobe(str(out)))
    assert 5.5 <= float(probe['format']['duration']) <= 6.5


def test_output_is_scaled_to_target_resolution(tmp_path: Path) -> None:
    """Whatever the source size, output is 1920x1080."""
    source = _synthetic_clip(tmp_path, seconds=5.0)
    result, _ = asyncio.run(normalize_clip(source, duration_s=3.0))
    out = tmp_path / 'scaled.mp4'
    out.write_bytes(result)
    probe = asyncio.run(async_ffprobe(str(out)))
    stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    assert int(stream['width']) == 1920
    assert int(stream['height']) == 1080


def test_output_has_no_audio_stream(tmp_path: Path) -> None:
    """Source audio is stripped — narration owns the audio track."""
    source = _synthetic_clip(tmp_path, seconds=5.0)
    result, _ = asyncio.run(normalize_clip(source, duration_s=3.0))
    out = tmp_path / 'noaudio.mp4'
    out.write_bytes(result)
    probe = asyncio.run(async_ffprobe(str(out)))
    assert not [s for s in probe['streams'] if s['codec_type'] == 'audio']
