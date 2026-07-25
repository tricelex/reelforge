"""Tests for the alignment stage (ElevenLabs FA + ASS subtitles)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.channels.models import Channel, ChannelKind
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    StageExecution,
    StageStatus,
)
from server.apps.pipelines.stages.alignment import (
    AlignmentStage,
    _build_ass_content,
    _map_aligned_words,
    _segment_from_alignment,
)
from server.common.exceptions import FatalProviderError


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
        'scene_breakdown': {
            'scenes': [
                {
                    'idx': 0,
                    'chapter_idx': 0,
                    'narration_text': 'Rome was',
                    'word_count': 2,
                },
            ],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.assets = AsyncMock()
    ctx.assets.save = AsyncMock(return_value=MagicMock(id='subtitle-uuid'))
    return ctx


def _fake_fa_result() -> dict[str, object]:
    return {
        'words': [
            {'text': 'Rome', 'start': 0.0, 'end': 0.4, 'loss': 0.1},
            {'text': 'was', 'start': 0.4, 'end': 0.7, 'loss': 0.05},
        ],
        'characters': [],
        'loss': 0.075,
    }


def test_alignment_stage_key() -> None:
    """AlignmentStage has the expected class attributes."""
    assert AlignmentStage.key == 'alignment'
    assert AlignmentStage.queue == 'api'


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


def test_offset_segment_and_scenes_shift_absolute_timeline() -> None:
    """Chapter-relative FA times gain a cumulative absolute offset."""
    from server.apps.pipelines.stages.alignment import (
        _offset_scenes,
        _offset_segment,
        _subtitle_segments_from_scenes,
    )

    segment = {
        'text': 'Hello world',
        'start': 0.1,
        'end': 2.0,
        'words': [
            {'word': 'Hello', 'start': 0.1, 'end': 0.5, 'score': 0.1},
            {'word': 'world', 'start': 0.6, 'end': 2.0, 'score': 0.1},
        ],
    }
    offset = _offset_segment(segment, 10.0)
    assert offset['start'] == 10.1
    assert offset['end'] == 12.0
    assert offset['words'][0]['start'] == 10.1

    scenes = _offset_scenes(
        [
            {
                'scene_idx': 1,
                'start_s': 0.1,
                'end_s': 2.0,
                'text': 'Hello world',
                'words': segment['words'],
            },
        ],
        10.0,
    )
    assert scenes[0]['start_s'] == 10.1
    assert scenes[0]['end_s'] == 12.0
    cues = _subtitle_segments_from_scenes(scenes)
    assert cues == [{'start': 10.1, 'end': 12.0, 'text': 'Hello world'}]


def test_subtitle_segments_chunk_words_by_four() -> None:
    """Long scenes emit multiple cues timed to word ends, not scene end."""
    from server.apps.pipelines.stages.alignment import (
        _subtitle_segments_from_scenes,
    )

    words = [
        {'word': f'w{i}', 'start': float(i), 'end': float(i) + 0.5}
        for i in range(9)
    ]
    cues = _subtitle_segments_from_scenes([
        {
            'scene_idx': 1,
            'start_s': 0.0,
            'end_s': 100.0,
            'text': 'ignored when words present',
            'words': words,
        },
    ])
    assert len(cues) == 3
    assert cues[0] == {'start': 0.0, 'end': 3.5, 'text': 'w0 w1 w2 w3'}
    assert cues[1] == {'start': 4.0, 'end': 7.5, 'text': 'w4 w5 w6 w7'}
    assert cues[2] == {'start': 8.0, 'end': 8.5, 'text': 'w8'}
    assert cues[-1]['end'] == 8.5
    assert cues[-1]['end'] != 100.0


def test_map_aligned_words_maps_text_and_loss() -> None:
    """ElevenLabs word fields map to word/start/end/score."""
    mapped = _map_aligned_words([
        {'text': 'Rome', 'start': 0.0, 'end': 0.4, 'loss': 0.12},
    ])
    assert mapped == [
        {'word': 'Rome', 'start': 0.0, 'end': 0.4, 'score': 0.12},
    ]


def test_segment_from_alignment_spans_words() -> None:
    """One segment covers first-word start through last-word end."""
    segment = _segment_from_alignment(
        'Rome was great.',
        {
            'words': [
                {'text': 'Rome', 'start': 0.1, 'end': 0.4, 'loss': 0.1},
                {'text': 'great', 'start': 1.0, 'end': 1.5, 'loss': 0.2},
            ],
        },
    )
    assert segment['start'] == 0.1
    assert segment['end'] == 1.5
    assert len(segment['words']) == 2


def test_split_words_into_scenes_assigns_scene_idx_and_skips_whitespace() -> None:
    """FA word stream is partitioned into scene_breakdown rows by word quota."""
    from server.apps.pipelines.stages.alignment import _split_words_into_scenes

    chapter_scenes = [
        {
            'idx': 10,
            'chapter_idx': 2,
            'narration_text': 'The fire did not',
            'word_count': 4,
        },
        {
            'idx': 11,
            'chapter_idx': 2,
            'narration_text': 'destroy Ashmere',
            'word_count': 2,
        },
    ]
    fa_words = [
        {'word': 'The', 'start': 0.1, 'end': 0.2, 'score': 0.1},
        {'word': ' ', 'start': 0.2, 'end': 0.25, 'score': 0.0},
        {'word': 'fire', 'start': 0.25, 'end': 0.5, 'score': 0.1},
        {'word': ' ', 'start': 0.5, 'end': 0.55, 'score': 0.0},
        {'word': 'did', 'start': 0.55, 'end': 0.7, 'score': 0.1},
        {'word': 'not', 'start': 0.7, 'end': 0.9, 'score': 0.1},
        {'word': 'destroy', 'start': 0.9, 'end': 1.2, 'score': 0.1},
        {'word': 'Ashmere', 'start': 1.2, 'end': 1.6, 'score': 0.1},
    ]
    result = _split_words_into_scenes(chapter_scenes, fa_words)
    assert len(result) == 2
    assert result[0]['scene_idx'] == 10
    assert result[0]['chapter_idx'] == 2
    assert result[0]['segment_idx'] == 0
    assert result[0]['start_s'] == 0.1
    assert result[0]['end_s'] == 0.9
    assert [w['word'] for w in result[0]['words']] == [
        'The',
        'fire',
        'did',
        'not',
    ]
    assert result[1]['scene_idx'] == 11
    assert result[1]['segment_idx'] == 1
    assert result[1]['start_s'] == 0.9
    assert result[1]['end_s'] == 1.6


def test_split_words_into_scenes_remap_when_quota_mismatches_fa_count() -> None:
    """When narration quotas disagree with FA count, remap proportionally."""
    from server.apps.pipelines.stages.alignment import _split_words_into_scenes

    chapter_scenes = [
        {
            'idx': 0,
            'chapter_idx': 0,
            'narration_text': 'one two three',
            'word_count': 3,
        },
        {
            'idx': 1,
            'chapter_idx': 0,
            'narration_text': 'four',
            'word_count': 1,
        },
    ]
    # 6 speech tokens vs quotas totaling 4 → proportional remap
    fa_words = [
        {'word': f'w{i}', 'start': float(i), 'end': float(i) + 0.5, 'score': 0}
        for i in range(6)
    ]
    result = _split_words_into_scenes(chapter_scenes, fa_words)
    assert len(result) == 2
    assert sum(len(s['words']) for s in result) == 6
    assert result[0]['end_s'] <= result[1]['start_s']


def test_split_words_into_scenes_raises_without_speech_words() -> None:
    """Empty / whitespace-only FA stream is a fatal alignment failure."""
    from server.apps.pipelines.stages.alignment import _split_words_into_scenes

    with pytest.raises(ValueError, match='no speech words'):
        _split_words_into_scenes(
            [
                {
                    'idx': 0,
                    'chapter_idx': 0,
                    'narration_text': 'Hello',
                    'word_count': 1,
                },
            ],
            [{'word': ' ', 'start': 0.0, 'end': 0.1, 'score': 0.0}],
        )


def test_alignment_run_returns_scenes_and_subtitle_asset() -> None:
    """run() returns dict with 'scenes' and 'ass_asset_id'."""
    ctx = _make_ctx()

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.pipelines.stages.alignment.load_tts_chapter_shards',
                new=AsyncMock(
                    return_value=[
                        {
                            'chapter_idx': 0,
                            'asset_id': 'audio-0',
                        },
                    ],
                ),
            ),
            patch(
                'server.apps.pipelines.stages.alignment._fetch_audio_bytes',
                new=AsyncMock(return_value=b'fake-audio'),
            ),
            patch(
                'server.apps.pipelines.stages.alignment.elevenlabs_client.force_align',
                new=AsyncMock(return_value=_fake_fa_result()),
            ),
            patch(
                'server.apps.pipelines.stages.alignment.settings.ELEVENLABS_API_KEY',
                'test-key',
            ),
        ):
            return await AlignmentStage().run(ctx)

    result = asyncio.run(_inner())
    assert 'scenes' in result
    assert 'ass_asset_id' in result
    assert result['chapter_origins'] == {0: 0.0}
    assert len(result['scenes']) == 1  # type: ignore[arg-type]
    assert result['scenes'][0]['scene_idx'] == 0  # type: ignore[index]
    ctx.costs.record.assert_awaited()


def test_alignment_run_fails_without_api_key() -> None:
    """run() fails fast when ELEVENLABS_API_KEY is unset."""
    ctx = _make_ctx()

    async def _inner() -> None:
        with patch(
            'server.apps.pipelines.stages.alignment.settings.ELEVENLABS_API_KEY',
            '',
        ):
            await AlignmentStage().run(ctx)

    with pytest.raises(FatalProviderError, match='ELEVENLABS_API_KEY'):
        asyncio.run(_inner())


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


@pytest.mark.django_db(transaction=True)
def test_alignment_loads_tts_from_child_executions() -> None:
    """Alignment reads TTS data from child rows, not stale parent shard aggregates."""
    channel = Channel.objects.create(
        name='Align DB Ch',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='align_db_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {
                    'key': 'alignment',
                    'depends_on': ['tts'],
                    'queue': 'api',
                },
            ],
        },
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot=bp.graph,
        topic='test',
    )
    parent = StageExecution.objects.create(
        run=run,
        stage_key='tts',
        status=StageStatus.SUCCEEDED,
        output={
            'shards': [
                {'shard_index': 0, 'status': StageStatus.SUCCEEDED},
            ],
        },
    )
    StageExecution.objects.create(
        run=run,
        stage_key='tts',
        parent=parent,
        shard_index=0,
        status=StageStatus.SUCCEEDED,
        output={
            'chapter_idx': 0,
            'asset_id': 'audio-ch0',
            'char_count': 100,
        },
    )

    ctx = MagicMock()
    ctx.run = run
    ctx.upstream = {
        'tts': {
            'shards': [{'shard_index': 0, 'status': StageStatus.SUCCEEDED}],
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
        'scene_breakdown': {
            'scenes': [
                {
                    'idx': 0,
                    'chapter_idx': 0,
                    'narration_text': 'Rome was',
                    'word_count': 2,
                },
            ],
        },
    }
    ctx.costs = AsyncMock()
    ctx.assets = AsyncMock()
    ctx.assets.save = AsyncMock(return_value=MagicMock(id='subtitle-uuid'))

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.pipelines.stages.alignment._fetch_audio_bytes',
                new=AsyncMock(return_value=b'fake-audio'),
            ),
            patch(
                'server.apps.pipelines.stages.alignment.elevenlabs_client.force_align',
                new=AsyncMock(return_value=_fake_fa_result()),
            ),
            patch(
                'server.apps.pipelines.stages.alignment.settings.ELEVENLABS_API_KEY',
                'test-key',
            ),
        ):
            return await AlignmentStage().run(ctx)

    result = asyncio.run(_inner())
    assert len(result['scenes']) == 1  # type: ignore[arg-type]
    assert result['scenes'][0]['chapter_idx'] == 0  # type: ignore[index]
    assert result['scenes'][0]['scene_idx'] == 0  # type: ignore[index]


@pytest.mark.django_db(transaction=True)
def test_alignment_fails_when_no_tts_children() -> None:
    """Alignment raises when no succeeded TTS child shards exist."""
    channel = Channel.objects.create(
        name='Align Empty',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='align_empty_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {
                    'key': 'alignment',
                    'depends_on': ['tts'],
                    'queue': 'api',
                },
            ],
        },
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot=bp.graph,
        topic='test',
    )

    ctx = MagicMock()
    ctx.run = run
    ctx.upstream = {'script': {'chapters': []}}
    ctx.costs = AsyncMock()

    with (
        patch(
            'server.apps.pipelines.stages.alignment.settings.ELEVENLABS_API_KEY',
            'test-key',
        ),
        pytest.raises(
            FatalProviderError,
            match='No succeeded TTS chapter shards',
        ),
    ):
        asyncio.run(AlignmentStage().run(ctx))
