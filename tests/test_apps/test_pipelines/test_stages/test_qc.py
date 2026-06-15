"""Tests for the QC pipeline stage."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.pipelines.stages.qc import (
    QCStage,
    _check_duration_drift,
    _run_silence_detect,
)
from server.common.exceptions import FatalProviderError

_PASSING_PROBE = {
    'streams': [
        {'codec_type': 'video', 'r_frame_rate': '30/1', 'codec_name': 'h264'},
        {'codec_type': 'audio', 'codec_name': 'aac'},
    ],
    'format': {'duration': '30.0'},
}

_PASSING_LOUDNESS = {'integrated': -14.0, 'tp': -1.5}


def _make_ctx(duration_s: float = 30.0) -> MagicMock:
    ctx = MagicMock()
    ctx.upstream = {
        'assembly': {'asset_id': 'final-uuid', 'duration_s': duration_s},
        'alignment': {
            'scenes': [
                {
                    'chapter_idx': 0,
                    'segment_idx': 0,
                    'start_s': 0.0,
                    'end_s': 5.0,
                    'text': 'A',
                    'words': [{'word': 'A', 'start': 0.1, 'end': 0.5}],
                },
            ],
            'ass_asset_id': 'sub-uuid',
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    return ctx


def test_qc_stage_attributes() -> None:
    assert QCStage.key == 'qc'
    assert QCStage.queue == 'render'
    assert QCStage.max_retries == 1
    assert QCStage.timeout_s == 600


def test_qc_fan_out_returns_none() -> None:
    assert QCStage().fan_out(MagicMock()) is None


def test_check_duration_drift_passes_within_tolerance() -> None:
    assert _check_duration_drift(30.0, 30.5) is None


def test_check_duration_drift_passes_zero_expected() -> None:
    assert _check_duration_drift(30.0, 0.0) is None


def test_check_duration_drift_returns_error_on_large_drift() -> None:
    result = _check_duration_drift(20.0, 30.0)
    assert result is not None
    assert result['check'] == 'duration_drift'


def test_run_silence_detect_parses_events() -> None:
    fake_stderr = (
        b'silence_start: 5.0\n'
        b'silence_end: 8.0 | silence_duration: 3.0\n'
    )
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', fake_stderr))

    async def _run() -> list:  # type: ignore[type-arg]
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            return await _run_silence_detect('/tmp/f.mp4')  # noqa: S108

    result = asyncio.run(_run())
    assert len(result) == 1
    assert result[0]['duration'] == 3.0


def test_run_silence_detect_empty_on_no_events() -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b'no silence here'))

    async def _run() -> list:  # type: ignore[type-arg]
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            return await _run_silence_detect('/tmp/f.mp4')  # noqa: S108

    assert asyncio.run(_run()) == []


def test_qc_run_passes_and_returns_report() -> None:
    ctx = _make_ctx(30.0)

    async def _run() -> dict:  # type: ignore[type-arg]
        with (
            patch(
                'server.apps.pipelines.stages.qc._fetch_asset_to_tempfile',
                new=AsyncMock(return_value='/tmp/final.mp4'),  # noqa: S108
            ),
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(return_value=_PASSING_PROBE),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_silence_detect',
                new=AsyncMock(return_value=[]),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_black_detect',
                new=AsyncMock(return_value=[]),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_freeze_detect',
                new=AsyncMock(return_value=[]),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_loudness_check',
                new=AsyncMock(return_value=_PASSING_LOUDNESS),
            ),
            patch.object(Path, 'unlink'),
        ):
            return await QCStage().run(ctx)

    result = asyncio.run(_run())
    assert result['passed'] is True
    assert 'qc_report' in result


def test_qc_raises_fatal_on_duration_drift() -> None:
    ctx = _make_ctx(30.0)
    probe = {**_PASSING_PROBE, 'format': {'duration': '20.0'}}

    async def _run() -> None:
        with (
            patch(
                'server.apps.pipelines.stages.qc._fetch_asset_to_tempfile',
                new=AsyncMock(return_value='/tmp/f.mp4'),  # noqa: S108
            ),
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(return_value=probe),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_silence_detect',
                new=AsyncMock(return_value=[]),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_black_detect',
                new=AsyncMock(return_value=[]),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_freeze_detect',
                new=AsyncMock(return_value=[]),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_loudness_check',
                new=AsyncMock(return_value=_PASSING_LOUDNESS),
            ),
            patch.object(Path, 'unlink'),
        ):
            await QCStage().run(ctx)

    with pytest.raises(FatalProviderError) as exc_info:
        asyncio.run(_run())
    assert exc_info.value.error_code == 'QC_FAILED'


def test_qc_raises_fatal_on_dead_air() -> None:
    ctx = _make_ctx(30.0)

    async def _run() -> None:
        with (
            patch(
                'server.apps.pipelines.stages.qc._fetch_asset_to_tempfile',
                new=AsyncMock(return_value='/tmp/f.mp4'),  # noqa: S108
            ),
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(return_value=_PASSING_PROBE),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_silence_detect',
                new=AsyncMock(
                    return_value=[
                        {'start': 5.0, 'end': 7.5, 'duration': 2.5}
                    ]
                ),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_black_detect',
                new=AsyncMock(return_value=[]),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_freeze_detect',
                new=AsyncMock(return_value=[]),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_loudness_check',
                new=AsyncMock(return_value=_PASSING_LOUDNESS),
            ),
            patch.object(Path, 'unlink'),
        ):
            await QCStage().run(ctx)

    with pytest.raises(FatalProviderError) as exc_info:
        asyncio.run(_run())
    assert 'dead_air' in str(exc_info.value)


def test_qc_raises_fatal_on_fps_mismatch() -> None:
    ctx = _make_ctx(30.0)
    probe = {
        'streams': [
            {
                'codec_type': 'video',
                'r_frame_rate': '25/1',
                'codec_name': 'h264',
            },
            {'codec_type': 'audio', 'codec_name': 'aac'},
        ],
        'format': {'duration': '30.0'},
    }

    async def _run() -> None:
        with (
            patch(
                'server.apps.pipelines.stages.qc._fetch_asset_to_tempfile',
                new=AsyncMock(return_value='/tmp/f.mp4'),  # noqa: S108
            ),
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(return_value=probe),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_silence_detect',
                new=AsyncMock(return_value=[]),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_black_detect',
                new=AsyncMock(return_value=[]),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_freeze_detect',
                new=AsyncMock(return_value=[]),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_loudness_check',
                new=AsyncMock(return_value=_PASSING_LOUDNESS),
            ),
            patch.object(Path, 'unlink'),
        ):
            await QCStage().run(ctx)

    with pytest.raises(FatalProviderError):
        asyncio.run(_run())


def test_qc_raises_fatal_on_loudness_out_of_range() -> None:
    ctx = _make_ctx(30.0)

    async def _run() -> None:
        with (
            patch(
                'server.apps.pipelines.stages.qc._fetch_asset_to_tempfile',
                new=AsyncMock(return_value='/tmp/f.mp4'),  # noqa: S108
            ),
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(return_value=_PASSING_PROBE),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_silence_detect',
                new=AsyncMock(return_value=[]),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_black_detect',
                new=AsyncMock(return_value=[]),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_freeze_detect',
                new=AsyncMock(return_value=[]),
            ),
            patch(
                'server.apps.pipelines.stages.qc._run_loudness_check',
                new=AsyncMock(return_value={'integrated': -20.0, 'tp': -1.5}),
            ),
            patch.object(Path, 'unlink'),
        ):
            await QCStage().run(ctx)

    with pytest.raises(FatalProviderError):
        asyncio.run(_run())
