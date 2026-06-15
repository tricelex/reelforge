"""Tests for the rendering.ffmpeg service module."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.rendering.ffmpeg import async_ffprobe


def test_rendering_app_importable() -> None:
    import server.apps.rendering.ffmpeg  # noqa: F401, PLC0415

    assert True


def test_async_ffprobe_returns_parsed_json() -> None:
    fake_output = b'{"streams": [], "format": {"duration": "30.0"}}'
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(fake_output, b''))

    async def _run() -> dict:  # type: ignore[type-arg]
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            return await async_ffprobe('/tmp/test.mp4')  # noqa: S108

    result = asyncio.run(_run())
    assert result['format']['duration'] == '30.0'
    assert result['streams'] == []


def test_async_ffprobe_raises_on_nonzero_exit() -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b'', b'no such file'))

    async def _run() -> None:
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            await async_ffprobe('/tmp/missing.mp4')  # noqa: S108

    try:
        asyncio.run(_run())
        raise AssertionError('expected RuntimeError')
    except RuntimeError as e:
        assert 'ffprobe failed' in str(e)
