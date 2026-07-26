"""Tests for the shared Ken Burns ffmpeg helper."""

import asyncio
from pathlib import Path

import pytest

from server.apps.rendering.ffmpeg import async_ffprobe, ken_burns


def _tiny_jpeg(tmp_path: Path) -> bytes:
    """Render a 320x240 solid-colour JPEG with ffmpeg and return its bytes."""
    out = tmp_path / 'src.jpg'

    async def _render() -> None:
        proc = await asyncio.create_subprocess_exec(
            'ffmpeg',
            '-y',
            '-f',
            'lavfi',
            '-i',
            'color=c=blue:s=320x240',
            '-frames:v',
            '1',
            str(out),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    asyncio.run(_render())
    return out.read_bytes()


def test_ken_burns_produces_a_video_of_requested_duration(
    tmp_path: Path,
) -> None:
    """A still image becomes an mp4 of roughly the requested length."""
    image_bytes = _tiny_jpeg(tmp_path)
    video_bytes = asyncio.run(ken_burns(image_bytes, duration_s=2.0))
    assert video_bytes
    out = tmp_path / 'out.mp4'
    out.write_bytes(video_bytes)
    probe = asyncio.run(async_ffprobe(str(out)))
    duration = float(probe['format']['duration'])
    assert 1.5 <= duration <= 2.5


def test_ken_burns_rejects_empty_image() -> None:
    """Empty input is a programming error, caught immediately."""
    with pytest.raises(AssertionError):
        asyncio.run(ken_burns(b'', duration_s=2.0))


def test_ken_burns_rejects_nonpositive_duration(tmp_path: Path) -> None:
    """Zero or negative duration is rejected before invoking ffmpeg."""
    image_bytes = _tiny_jpeg(tmp_path)
    with pytest.raises(AssertionError):
        asyncio.run(ken_burns(image_bytes, duration_s=0.0))


def test_ken_burns_preset_index_wraps(tmp_path: Path) -> None:
    """preset_idx beyond the preset count wraps instead of raising."""
    image_bytes = _tiny_jpeg(tmp_path)
    video_bytes = asyncio.run(
        ken_burns(image_bytes, duration_s=1.0, preset_idx=99),
    )
    assert video_bytes
