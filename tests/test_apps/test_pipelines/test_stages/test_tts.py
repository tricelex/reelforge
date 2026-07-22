"""Tests for the tts fan-out stage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.pipelines.stages.tts import TtsStage
from server.common.exceptions import FatalProviderError


def _make_ctx(n_chapters: int = 2) -> MagicMock:
    ctx = MagicMock()
    ctx.run.prompt_snapshot = {}
    ctx.channel.voice_id = 'EXAVITQu4vr4xnSDxMaL'
    ctx.channel.stability = 0.5
    ctx.channel.similarity_boost = 0.75
    ctx.execution.shard_index = None
    ctx.execution.parent_id = None
    ctx.upstream = {
        'script': {
            'chapters': [
                {
                    'idx': i,
                    'text': 'Chapter text here.',
                    'word_count': 3,
                    'title': f'Ch {i}',
                    'closing_line': 'End.',
                }
                for i in range(n_chapters)
            ],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.assets = AsyncMock()
    ctx.assets.save = AsyncMock(return_value=MagicMock(id='audio-uuid'))
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    ctx.prompts.get_model = AsyncMock(return_value=None)
    return ctx


def test_tts_stage_key() -> None:
    """TtsStage has the expected class attributes."""
    assert TtsStage.key == 'tts'
    assert TtsStage.queue == 'api'


def test_tts_fan_out_returns_one_per_chapter() -> None:
    """fan_out() returns one shard per script chapter."""
    ctx = _make_ctx(n_chapters=4)
    shards = TtsStage().fan_out(ctx)
    assert shards is not None
    assert len(shards) == 4
    assert shards[0]['chapter_idx'] == 0
    assert shards[3]['chapter_idx'] == 3


def test_tts_child_run_saves_audio_asset() -> None:
    """A child shard execution synthesises audio and saves it as an asset."""
    ctx = _make_ctx()
    ctx.execution.shard_index = 0
    ctx.execution.parent_id = 'parent-id'
    ctx.execution.input_snapshot = {
        'chapter_idx': 0,
        'text': 'Chapter text here.',
    }

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.elevenlabs.synthesize',
            new=AsyncMock(return_value=b'fake-mp3'),
        ):
            return await TtsStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['chapter_idx'] == 0
    assert 'asset_id' in result
    assert result['char_count'] == len('Chapter text here.')


def test_tts_run_raises_when_api_key_missing(settings) -> None:
    """run() fails fast with a clear error when ELEVENLABS_API_KEY is unset."""
    settings.ELEVENLABS_API_KEY = ''
    ctx = _make_ctx()
    ctx.execution.shard_index = 0
    ctx.execution.parent_id = 'parent-id'
    ctx.execution.input_snapshot = {
        'chapter_idx': 0,
        'text': 'Chapter text here.',
    }

    async def _inner() -> None:
        with pytest.raises(FatalProviderError, match='ELEVENLABS_API_KEY'):
            await TtsStage().run(ctx)

    asyncio.run(_inner())
