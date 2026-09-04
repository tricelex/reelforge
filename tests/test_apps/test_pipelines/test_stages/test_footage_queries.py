"""Tests for the footage_queries stage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.pipelines.schemas import FootageQueriesOutput, FootageQuery
from server.apps.pipelines.stages.footage_queries import FootageQueriesStage
from server.common.exceptions import FatalProviderError


def _make_ctx(n_scenes: int = 3) -> MagicMock:
    ctx = MagicMock()
    ctx.run.topic = 'Battle of Midway'
    ctx.run.id = 'run-uuid'
    ctx.run.prompt_snapshot = {}
    ctx.channel.niche_config = None
    ctx.upstream = {
        'scene_breakdown': {
            'scenes': [
                {
                    'idx': i,
                    'chapter_idx': 0,
                    'visual_concept': f'concept {i}',
                    'narration_text': f'narration {i}',
                    'est_seconds': 8.0,
                }
                for i in range(n_scenes)
            ],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    ctx.prompts.get_model = AsyncMock(return_value=None)
    return ctx


def _output(scene_idxs: list[int]) -> FootageQueriesOutput:
    return FootageQueriesOutput(
        queries=[
            FootageQuery(
                scene_idx=i,
                primary_query=f'query {i}',
                fallback_queries=[f'broad {i}'],
                ai_fallback_prompt=f'ai {i}',
            )
            for i in scene_idxs
        ],
    )


def test_stage_key_and_queue() -> None:
    """The stage registers under the expected key and queue."""
    assert FootageQueriesStage.key == 'footage_queries'
    assert FootageQueriesStage.queue == 'api'


def test_run_returns_one_query_per_scene() -> None:
    """Full scene coverage produces a query per scene."""
    ctx = _make_ctx(n_scenes=3)
    with patch(
        'server.apps.generation.clients.llm.run_agent',
        new=AsyncMock(return_value=_output([0, 1, 2])),
    ):
        result = asyncio.run(FootageQueriesStage().run(ctx))
    assert len(result['queries']) == 3
    assert result['queries'][0]['primary_query'] == 'query 0'
    assert result['queries'][0]['ai_fallback_prompt'] == 'ai 0'


def test_run_raises_when_scene_breakdown_is_empty() -> None:
    """No scenes upstream is a fatal configuration error."""
    ctx = _make_ctx(n_scenes=0)
    with patch(
        'server.apps.generation.clients.llm.run_agent',
        new=AsyncMock(return_value=_output([])),
    ):
        with pytest.raises(FatalProviderError) as exc_info:
            asyncio.run(FootageQueriesStage().run(ctx))
    assert exc_info.value.error_code == 'missing_scenes'


def test_run_raises_on_coverage_mismatch() -> None:
    """A missing scene query is fatal, not silently tolerated."""
    ctx = _make_ctx(n_scenes=3)
    with patch(
        'server.apps.generation.clients.llm.run_agent',
        new=AsyncMock(return_value=_output([0, 1])),
    ):
        with pytest.raises(FatalProviderError) as exc_info:
            asyncio.run(FootageQueriesStage().run(ctx))
    assert exc_info.value.error_code == 'query_coverage'
    assert '2' in str(exc_info.value)


def test_run_raises_on_extra_queries() -> None:
    """A query for a nonexistent scene is also a coverage failure."""
    ctx = _make_ctx(n_scenes=2)
    with patch(
        'server.apps.generation.clients.llm.run_agent',
        new=AsyncMock(return_value=_output([0, 1, 7])),
    ):
        with pytest.raises(FatalProviderError) as exc_info:
            asyncio.run(FootageQueriesStage().run(ctx))
    assert exc_info.value.error_code == 'query_coverage'


def test_run_batches_by_chapter() -> None:
    """One LLM call per chapter, then queries are concatenated.

    A single call across every scene risks truncation at the model's
    max_tokens on long-form runs with many scenes, silently dropping
    trailing queries. Batching per chapter keeps each call small.
    """
    ctx = _make_ctx(n_scenes=0)
    ctx.upstream['scene_breakdown']['scenes'] = [
        {'idx': 0, 'chapter_idx': 0, 'visual_concept': 'a'},
        {'idx': 1, 'chapter_idx': 0, 'visual_concept': 'b'},
        {'idx': 2, 'chapter_idx': 1, 'visual_concept': 'c'},
    ]
    mock_agent = AsyncMock(
        side_effect=[
            _output([0, 1]),
            _output([2]),
        ],
    )
    with patch(
        'server.apps.generation.clients.llm.run_agent',
        new=mock_agent,
    ):
        result = asyncio.run(FootageQueriesStage().run(ctx))
    assert mock_agent.await_count == 2
    assert [q['scene_idx'] for q in result['queries']] == [0, 1, 2]
