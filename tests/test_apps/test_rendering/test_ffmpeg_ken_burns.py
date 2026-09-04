"""Tests for the shared Ken Burns ffmpeg helper."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.rendering.ffmpeg import (
    _KEN_BURNS_PAN_ZOOM,
    _KEN_BURNS_TARGET_ZOOM,
    _ken_burns_filters,
    async_ffprobe,
    ken_burns,
)


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
    with pytest.raises(ValueError, match='image_bytes must be non-empty'):
        asyncio.run(ken_burns(b'', duration_s=2.0))


def test_ken_burns_rejects_nonpositive_duration(tmp_path: Path) -> None:
    """Zero or negative duration is rejected before invoking ffmpeg."""
    image_bytes = _tiny_jpeg(tmp_path)
    with pytest.raises(ValueError, match='duration_s must be > 0'):
        asyncio.run(ken_burns(image_bytes, duration_s=0.0))


def test_ken_burns_rejects_empty_ffmpeg_output() -> None:
    """A successful process that writes no video is rejected."""
    process = MagicMock()
    process.returncode = 0
    process.communicate = AsyncMock(return_value=(b'', b''))

    with (
        patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=process),
        ),
        patch('pathlib.Path.read_bytes', return_value=b''),
    ):
        with pytest.raises(RuntimeError, match='produced empty video'):
            asyncio.run(ken_burns(b'image', duration_s=1.0))


def test_ken_burns_preset_index_wraps(tmp_path: Path) -> None:
    """preset_idx beyond the preset count wraps instead of raising."""
    image_bytes = _tiny_jpeg(tmp_path)
    video_bytes = asyncio.run(
        ken_burns(image_bytes, duration_s=1.0, preset_idx=99),
    )
    assert video_bytes


def test_ken_burns_handles_subframe_duration_without_zero_frames(
    tmp_path: Path,
) -> None:
    """A duration shorter than one frame still renders at least one frame."""
    image_bytes = _tiny_jpeg(tmp_path)
    video_bytes = asyncio.run(ken_burns(image_bytes, duration_s=0.01))
    assert video_bytes


@pytest.mark.parametrize('duration_s', [5.0, 12.0, 30.0])
def test_ken_burns_duration_scales_correctly_at_long_holds(
    tmp_path: Path,
    duration_s: float,
) -> None:
    """Long documentary-style holds still land on the requested duration.

    This is the gap the fixed-per-frame-delta bug hid: short clips near the
    original 5s tuning always probed fine, but nothing exercised 12s/30s.
    """
    image_bytes = _tiny_jpeg(tmp_path)
    video_bytes = asyncio.run(ken_burns(image_bytes, duration_s=duration_s))
    assert video_bytes
    out = tmp_path / f'out_{int(duration_s)}.mp4'
    out.write_bytes(video_bytes)
    probe = asyncio.run(async_ffprobe(str(out)))
    duration = float(probe['format']['duration'])
    assert duration_s - 1.0 <= duration <= duration_s + 1.0


@pytest.mark.parametrize('preset_idx', range(7))
def test_ken_burns_every_preset_renders_at_a_long_hold(
    tmp_path: Path,
    preset_idx: int,
) -> None:
    """Each preset is valid ffmpeg syntax, not just preset 0."""
    image_bytes = _tiny_jpeg(tmp_path)
    video_bytes = asyncio.run(
        ken_burns(image_bytes, duration_s=10.0, preset_idx=preset_idx),
    )
    assert video_bytes


class TestKenBurnsFilters:
    """Tests for the pure filter-string builder behind ken_burns()."""

    def test_returns_seven_presets(self) -> None:
        """Enough motion variety that a 100+ scene run doesn't repeat fast."""
        assert len(_ken_burns_filters(150)) == 7

    def test_zoom_presets_target_the_same_zoom_regardless_of_duration(
        self,
    ) -> None:
        """The target zoom is a fixed constant, not a per-frame rate."""
        short = _ken_burns_filters(150)  # 5s @ 30fps
        long = _ken_burns_filters(900)  # 30s @ 30fps
        target = str(_KEN_BURNS_TARGET_ZOOM)
        assert target in short[0]
        assert target in long[0]
        assert target in short[1]
        assert target in long[1]

    def test_easing_denominator_scales_with_frame_count(self) -> None:
        """The easing fraction is normalised against this call's own frames."""
        short = _ken_burns_filters(150)
        long = _ken_burns_filters(900)
        assert 'on/149' in short[0]
        assert 'on/899' in long[0]

    def test_pan_presets_use_a_fixed_zoom_for_a_bounded_margin(self) -> None:
        """Pan margin derives from a fixed zoom, not an unbounded pixel count.

        That bound is what keeps panning from running past the source
        image's edge on a long hold.
        """
        filters = _ken_burns_filters(900)
        pan_zoom = str(_KEN_BURNS_PAN_ZOOM)
        assert f'z={pan_zoom}' in filters[2]
        assert f'z={pan_zoom}' in filters[3]

    def test_frame_count_is_embedded_in_every_preset(self) -> None:
        """d= matches the caller's requested frame count, not a placeholder."""
        for vf in _ken_burns_filters(212):
            assert 'd=212' in vf
