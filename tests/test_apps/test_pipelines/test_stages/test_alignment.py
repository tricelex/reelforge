"""Tests for the alignment stage (WhisperX + ASS subtitles)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.alignment import (
    AlignmentStage,
    _build_ass_content,
)


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.prompt_snapshot = {}
    ctx.execution.shard_index = None
    ctx.execution.parent_id = None
    ctx.upstream = {
        'tts': {
            'shards': [
                {
                    'shard_index': 0,
                    'chapter_idx': 0,
                    'asset_id': 'audio-0',
                    'char_count': 100,
                },
            ],
        },
        'script': {
            'chapters': [
                {
                    'idx': 0,
                    'text': 'Rome was great once. Then it fell.',
                    'word_count': 8,
                },
            ],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.assets = AsyncMock()
    ctx.assets.save = AsyncMock(return_value=MagicMock(id='subtitle-uuid'))
    return ctx


def test_alignment_stage_key() -> None:
    """AlignmentStage has the expected class attributes."""
    assert AlignmentStage.key == 'alignment'
    assert AlignmentStage.queue == 'gpu'


def test_alignment_fan_out_none() -> None:
    """Alignment is a single-execution stage."""
    assert AlignmentStage().fan_out(MagicMock()) is None


def test_build_ass_content_produces_dialogue_lines() -> None:
    """_build_ass_content writes one Dialogue line per segment."""
    segments = [
        {'start': 0.0, 'end': 2.5, 'text': 'Rome was great.'},
        {'start': 2.6, 'end': 5.0, 'text': 'Then it fell.'},
    ]
    content = _build_ass_content(segments).decode()
    assert (
        'Dialogue: 0,0:00:00.00,0:00:02.50,Default,Rome was great.' in content
    )
    assert 'Dialogue: 0,0:00:02.60,0:00:05.00,Default,Then it fell.' in content


def test_build_srt_content_formats_timestamps() -> None:
    """_build_srt_content emits numbered SRT blocks with comma-ms timestamps."""
    from server.apps.pipelines.stages.alignment import _build_srt_content

    segments = [
        {'start': 0.0, 'end': 2.5, 'text': 'In 476 AD,'},
        {'start': 2.5, 'end': 7.4, 'text': 'the last Roman emperor fell.'},
    ]
    srt = _build_srt_content(segments).decode()
    assert '1\n00:00:00,000 --> 00:00:02,500\nIn 476 AD,' in srt
    assert (
        '2\n00:00:02,500 --> 00:00:07,400\nthe last Roman emperor fell.' in srt
    )


def test_fmt_srt_time_carries_millisecond_rounding_into_seconds() -> None:
    """A fractional part that rounds up to 1000ms carries into the next second.

    Instead of emitting an invalid 4-digit millisecond field.
    """
    from server.apps.pipelines.stages.alignment import _fmt_srt_time

    assert _fmt_srt_time(1.9996) == '00:00:02,000'
    assert _fmt_srt_time(59.9997) == '00:01:00,000'
    assert _fmt_srt_time(3599.9996) == '01:00:00,000'
    assert _fmt_srt_time(0.0) == '00:00:00,000'
    assert _fmt_srt_time(61.234) == '00:01:01,234'


def test_alignment_run_returns_scenes_and_subtitle_asset() -> None:
    """run() returns dict with 'scenes' and 'ass_asset_id'."""
    ctx = _make_ctx()
    fake_whisper_result = {
        'segments': [
            {
                'start': 0.0,
                'end': 2.5,
                'text': 'Rome was great once.',
                'words': [{'word': 'Rome', 'start': 0.0, 'end': 0.4}],
            },
        ],
    }

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.pipelines.stages.alignment._fetch_audio_bytes',
                new=AsyncMock(return_value=b'fake-audio'),
            ),
            patch(
                'server.apps.generation.clients.whisperx.align',
                new=AsyncMock(return_value=fake_whisper_result),
            ),
        ):
            return await AlignmentStage().run(ctx)

    result = asyncio.run(_inner())
    assert 'scenes' in result
    assert 'ass_asset_id' in result
    assert len(result['scenes']) == 1  # type: ignore[arg-type]


def test_fetch_audio_bytes_reads_from_asset() -> None:
    """_fetch_audio_bytes returns the bytes from asset.file.read()."""
    from server.apps.pipelines.stages.alignment import (
        _fetch_audio_bytes,
    )

    mock_asset = MagicMock()
    mock_asset.file.read.return_value = b'audio-bytes'

    async def _inner() -> bytes:
        with patch(
            'server.apps.assets.models.Asset.objects.aget',
            new=AsyncMock(return_value=mock_asset),
        ):
            return await _fetch_audio_bytes('some-uuid')

    result = asyncio.run(_inner())
    assert result == b'audio-bytes'
