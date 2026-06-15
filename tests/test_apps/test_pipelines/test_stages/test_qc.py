"""Tests for the QC pipeline stage."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.pipelines.stages.qc import (
    QCStage,
    _check_duration_drift,  # noqa: PLC2701
    _fetch_asset_to_tempfile,  # noqa: PLC2701
    _parse_fps,  # noqa: PLC2701
    _run_black_detect,  # noqa: PLC2701
    _run_freeze_detect,  # noqa: PLC2701
    _run_loudness_check,  # noqa: PLC2701
    _run_silence_detect,  # noqa: PLC2701
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
                        {'start': 5.0, 'end': 7.5, 'duration': 2.5},
                    ],
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


# ---------------------------------------------------------------------------
# _fetch_asset_to_tempfile
# ---------------------------------------------------------------------------


def test_fetch_asset_to_tempfile_writes_content_and_returns_path() -> None:
    """_fetch_asset_to_tempfile writes asset bytes to a temp file."""
    fake_asset = MagicMock()

    async def _run() -> str:
        with (
            patch(
                'server.apps.assets.models.Asset.objects.aget',
                new=AsyncMock(return_value=fake_asset),
            ),
            patch(
                'asyncio.to_thread',
                new=AsyncMock(return_value=b'mp4 content'),
            ),
        ):
            return await _fetch_asset_to_tempfile('asset-uuid')

    path = asyncio.run(_run())
    assert path.endswith('.mp4')
    # Clean up with Path.unlink(missing_ok=True) — no branch to miss
    Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# _parse_fps
# ---------------------------------------------------------------------------


def test_parse_fps_with_slash_notation() -> None:
    assert _parse_fps('30/1') == 30.0


def test_parse_fps_with_zero_denominator() -> None:
    assert _parse_fps('30/0') == 0.0


def test_parse_fps_plain_float_string() -> None:
    """_parse_fps returns float when no '/' present (line 58)."""
    assert _parse_fps('25.0') == 25.0


# ---------------------------------------------------------------------------
# _run_black_detect
# ---------------------------------------------------------------------------


def test_run_black_detect_parses_events() -> None:
    fake_stderr = (
        b'[blackdetect @ 0x...] '
        b'black_start:2.0 black_end:3.0 black_duration:1.0\n'
    )
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', fake_stderr))

    async def _run() -> list:  # type: ignore[type-arg]
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            return await _run_black_detect('/tmp/f.mp4')  # noqa: S108

    result = asyncio.run(_run())
    assert len(result) == 1
    assert result[0]['duration'] == 1.0
    assert result[0]['start'] == 2.0
    assert result[0]['end'] == 3.0


def test_run_black_detect_empty_on_no_events() -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b'nothing here'))

    async def _run() -> list:  # type: ignore[type-arg]
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            return await _run_black_detect('/tmp/f.mp4')  # noqa: S108

    assert asyncio.run(_run()) == []


# ---------------------------------------------------------------------------
# _run_freeze_detect
# ---------------------------------------------------------------------------


def test_run_freeze_detect_parses_long_freeze() -> None:
    """Freeze events longer than _BLACK_FREEZE_MAX_S (0.5s) are returned."""
    fake_stderr = b'freeze_start: 1.0\nfreeze_end: 2.0\n'
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', fake_stderr))

    async def _run() -> list:  # type: ignore[type-arg]
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            return await _run_freeze_detect('/tmp/f.mp4')  # noqa: S108

    result = asyncio.run(_run())
    assert len(result) == 1
    assert result[0]['duration'] == pytest.approx(1.0)


def test_run_freeze_detect_excludes_short_freezes() -> None:
    """Freeze events <= _BLACK_FREEZE_MAX_S are filtered out."""
    # 0.3 s freeze — below 0.5 s threshold
    fake_stderr = b'freeze_start: 1.0\nfreeze_end: 1.3\n'
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', fake_stderr))

    async def _run() -> list:  # type: ignore[type-arg]
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            return await _run_freeze_detect('/tmp/f.mp4')  # noqa: S108

    assert asyncio.run(_run()) == []


def test_run_freeze_detect_empty_on_no_events() -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b'no freeze'))

    async def _run() -> list:  # type: ignore[type-arg]
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            return await _run_freeze_detect('/tmp/f.mp4')  # noqa: S108

    assert asyncio.run(_run()) == []


# ---------------------------------------------------------------------------
# _run_loudness_check
# ---------------------------------------------------------------------------


def test_run_loudness_check_parses_integrated_and_tp() -> None:
    fake_stderr = (
        b'  I: -14.0 LUFS\n'
        b'  True peak: -2.0 dBFS\n'
    )
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', fake_stderr))

    async def _run() -> dict:  # type: ignore[type-arg]
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            return await _run_loudness_check('/tmp/f.mp4')  # noqa: S108

    result = asyncio.run(_run())
    assert result['integrated'] == pytest.approx(-14.0)
    assert result['tp'] == pytest.approx(-2.0)


def test_run_loudness_check_uses_defaults_when_not_found() -> None:
    """_run_loudness_check returns defaults when ffmpeg output has no match."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b'no loudness data'))

    async def _run() -> dict:  # type: ignore[type-arg]
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            return await _run_loudness_check('/tmp/f.mp4')  # noqa: S108

    result = asyncio.run(_run())
    assert result['integrated'] == -14.0
    assert result['tp'] == -1.0


def test_run_loudness_check_handles_malformed_integrated_line() -> None:
    """Lines with 'I:' but unparseable value fall back to the default."""
    fake_stderr = b'  I: bad LUFS\n'
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', fake_stderr))

    async def _run() -> dict:  # type: ignore[type-arg]
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            return await _run_loudness_check('/tmp/f.mp4')  # noqa: S108

    result = asyncio.run(_run())
    assert result['integrated'] == -14.0


def test_run_loudness_check_handles_malformed_tp_line() -> None:
    """Lines with 'True peak:' but unparseable value fall back to default."""
    # Provide a line where splitting on 'dBFS' gives a non-numeric string
    fake_stderr = b'  True peak: bad dBFS\n'
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', fake_stderr))

    async def _run() -> dict:  # type: ignore[type-arg]
        with patch(
            'asyncio.create_subprocess_exec',
            new=AsyncMock(return_value=mock_proc),
        ):
            return await _run_loudness_check('/tmp/f.mp4')  # noqa: S108

    result = asyncio.run(_run())
    assert result['tp'] == -1.0


# ---------------------------------------------------------------------------
# QCStage.run — additional branch coverage
# ---------------------------------------------------------------------------


def test_qc_raises_fatal_when_no_video_stream() -> None:
    """QC fails with av_sync/no_video_stream when probe has no video streams."""
    ctx = _make_ctx(30.0)
    probe = {
        'streams': [
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

    with pytest.raises(FatalProviderError) as exc_info:
        asyncio.run(_run())
    assert 'av_sync' in str(exc_info.value)


def test_qc_raises_fatal_when_no_audio_stream() -> None:
    """QC fails with av_sync/no_audio_stream when probe has no audio streams."""
    ctx = _make_ctx(30.0)
    probe = {
        'streams': [
            {'codec_type': 'video', 'r_frame_rate': '30/1'},
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

    with pytest.raises(FatalProviderError) as exc_info:
        asyncio.run(_run())
    assert 'av_sync' in str(exc_info.value)


def test_qc_silence_below_threshold_does_not_add_failure() -> None:
    """Silence events shorter than _SILENCE_MAX_S (1.8s) are ignored."""
    ctx = _make_ctx(30.0)

    async def _run() -> dict:  # type: ignore[type-arg]
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
                    return_value=[{'start': 5.0, 'end': 6.0, 'duration': 1.0}],
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
            return await QCStage().run(ctx)

    result = asyncio.run(_run())
    assert result['passed'] is True


def test_qc_black_frames_below_threshold_does_not_fail() -> None:
    """Black frame events <= _BLACK_FREEZE_MAX_S do not trigger failure."""
    ctx = _make_ctx(30.0)

    async def _run() -> dict:  # type: ignore[type-arg]
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
                # duration 0.3 s — below the 0.5 s threshold
                new=AsyncMock(
                    return_value=[
                        {'start': 0.0, 'end': 0.3, 'duration': 0.3},
                    ],
                ),
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


def test_qc_raises_fatal_on_black_frames() -> None:
    """QC fails when black frames exceed _BLACK_FREEZE_MAX_S threshold."""
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
                new=AsyncMock(
                    return_value=[
                        {'start': 0.0, 'end': 1.0, 'duration': 1.0},
                    ],
                ),
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
    assert 'black_frames' in str(exc_info.value)


def test_qc_raises_fatal_on_frozen_frames() -> None:
    """QC fails when freeze events are detected."""
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
                new=AsyncMock(
                    return_value=[
                        {'start': 2.0, 'end': 4.0, 'duration': 2.0},
                    ],
                ),
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
    assert 'frozen_frames' in str(exc_info.value)


def test_qc_raises_fatal_on_true_peak_exceeded() -> None:
    """QC fails when true peak loudness exceeds _LOUDNESS_MAX_TP (-1.0 dBTP)."""
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
                # integrated is fine, but true peak is above -1.0
                new=AsyncMock(return_value={'integrated': -14.0, 'tp': -0.5}),
            ),
            patch.object(Path, 'unlink'),
        ):
            await QCStage().run(ctx)

    with pytest.raises(FatalProviderError) as exc_info:
        asyncio.run(_run())
    assert 'true_peak' in str(exc_info.value)
