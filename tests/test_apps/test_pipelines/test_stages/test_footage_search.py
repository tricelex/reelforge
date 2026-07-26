"""Tests for the footage_search fan-out stage and its fallback cascade."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.generation.clients.stock.base import FootageCandidate
from server.apps.pipelines.stages.footage_search import FootageSearchStage
from server.common.exceptions import FatalProviderError


def _candidate(external_id: str = '1') -> FootageCandidate:
    return FootageCandidate(
        provider='pexels',
        external_id=external_id,
        media_type='video',
        download_url='https://e.test/v.mp4',
        thumb_url='https://e.test/t.jpg',
        source_page_url='https://e.test/p',
        width=1920,
        height=1080,
        duration_s=10.0,
        license='pexels',
        license_url='',
        author='A',
        attribution_required=False,
        title='ocean',
        tags=(),
    )


def _make_ctx(*, ai_fallback: bool = True, rerank: str = 'none') -> MagicMock:
    ctx = MagicMock()
    ctx.run.id = 'run-uuid'
    ctx.run.topic = 'Oceans'
    config = MagicMock()
    config.enabled_providers = ['pexels']
    config.ai_fallback_enabled = ai_fallback
    config.rerank_mode = rerank
    config.candidates_per_scene = 8
    config.min_clip_width = 1280
    config.min_clip_duration_s = 3.0
    config.allowed_licenses = []
    ctx.channel.footage_sourcing_or_default.return_value = config
    ctx.upstream = {
        'footage_queries': {
            'queries': [
                {
                    'scene_idx': 0,
                    'primary_query': 'ocean waves',
                    'fallback_queries': ['ocean'],
                    'media_preference': 'video',
                    'orientation': 'landscape',
                    'era_hint': '',
                    'negative_terms': [],
                    'ai_fallback_prompt': 'a stormy ocean',
                },
            ],
        },
        'scene_breakdown': {
            'scenes': [{'idx': 0, 'visual_concept': 'ocean waves'}],
        },
    }
    ctx.execution.input_snapshot = {
        'scene_idx': 0,
        'primary_query': 'ocean waves',
        'fallback_queries': ['ocean'],
        'media_preference': 'video',
        'orientation': 'landscape',
        'negative_terms': [],
        'ai_fallback_prompt': 'a stormy ocean',
        'visual_concept': 'ocean waves',
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.assets = AsyncMock()
    ctx.assets.save = AsyncMock(return_value=MagicMock(id='asset-uuid'))
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    ctx.prompts.get_model = AsyncMock(return_value=None)
    return ctx


def test_stage_key_and_queue() -> None:
    """The stage registers under the expected key and queue."""
    assert FootageSearchStage.key == 'footage_search'
    assert FootageSearchStage.queue == 'api'


def test_fan_out_returns_one_shard_per_query() -> None:
    """Fan-out shards carry the query plus the scene's visual concept."""
    ctx = _make_ctx()
    shards = FootageSearchStage().fan_out(ctx)
    assert shards is not None
    assert len(shards) == 1
    assert shards[0]['scene_idx'] == 0
    assert shards[0]['primary_query'] == 'ocean waves'
    assert shards[0]['visual_concept'] == 'ocean waves'


def _patched_download() -> object:
    return patch(
        'server.apps.pipelines.stages.footage_search._download_and_validate',
        new=AsyncMock(return_value=(b'bytes', 'video/mp4')),
    )


def test_primary_query_hit_selects_a_candidate() -> None:
    """A direct hit downloads and records the selected candidate."""
    ctx = _make_ctx()
    with (
        patch(
            'server.apps.pipelines.stages.footage_search.search_candidates',
            new=AsyncMock(return_value=[_candidate('1')]),
        ),
        _patched_download(),
        patch(
            'server.apps.pipelines.stages.footage_search._record_credit',
            new=AsyncMock(),
        ),
    ):
        result = asyncio.run(FootageSearchStage().run(ctx))
    assert result['scene_idx'] == 0
    assert result['source'] == 'pexels'
    assert result['asset_id'] == 'asset-uuid'
    assert result['media_type'] == 'video'
    assert len(result['candidates']) == 1


def test_broadens_to_fallback_query_when_primary_is_empty() -> None:
    """An empty primary result retries with the broadened query."""
    ctx = _make_ctx()
    search = AsyncMock(side_effect=[[], [_candidate('2')]])
    with (
        patch(
            'server.apps.pipelines.stages.footage_search.search_candidates',
            new=search,
        ),
        _patched_download(),
        patch(
            'server.apps.pipelines.stages.footage_search._record_credit',
            new=AsyncMock(),
        ),
    ):
        result = asyncio.run(FootageSearchStage().run(ctx))
    assert search.await_count == 2
    assert result['source'] == 'pexels'


def test_falls_back_to_ai_generation_when_nothing_found() -> None:
    """Exhausted queries fall through to AI image generation."""
    ctx = _make_ctx(ai_fallback=True)
    with (
        patch(
            'server.apps.pipelines.stages.footage_search.search_candidates',
            new=AsyncMock(return_value=[]),
        ),
        patch(
            'server.apps.generation.clients.fal.generate_image',
            new=AsyncMock(return_value={'url': 'https://fal/x.png'}),
        ),
        patch(
            'server.apps.pipelines.stages.footage_search._fetch_bytes',
            new=AsyncMock(return_value=b'img'),
        ),
    ):
        result = asyncio.run(FootageSearchStage().run(ctx))
    assert result['source'] == 'ai_flux'
    assert result['media_type'] == 'image'
    assert result['candidates'] == []


def test_parks_when_nothing_found_and_ai_disabled() -> None:
    """With AI disabled, an exhausted cascade parks the scene."""
    ctx = _make_ctx(ai_fallback=False)
    with patch(
        'server.apps.pipelines.stages.footage_search.search_candidates',
        new=AsyncMock(return_value=[]),
    ):
        with pytest.raises(FatalProviderError) as exc_info:
            asyncio.run(FootageSearchStage().run(ctx))
    assert exc_info.value.error_code == 'no_footage_found'


def test_corrupt_download_falls_through_to_next_candidate() -> None:
    """A candidate that fails ffprobe validation is skipped."""
    ctx = _make_ctx()
    download = AsyncMock(side_effect=[None, (b'bytes', 'video/mp4')])
    with (
        patch(
            'server.apps.pipelines.stages.footage_search.search_candidates',
            new=AsyncMock(return_value=[_candidate('1'), _candidate('2')]),
        ),
        patch(
            'server.apps.pipelines.stages.footage_search._download_and_validate',
            new=download,
        ),
        patch(
            'server.apps.pipelines.stages.footage_search._record_credit',
            new=AsyncMock(),
        ),
    ):
        result = asyncio.run(FootageSearchStage().run(ctx))
    assert download.await_count == 2
    assert result['asset_id'] == 'asset-uuid'


def test_vision_failure_degrades_to_metadata_ranking() -> None:
    """A failed vision call must not fail the scene."""
    ctx = _make_ctx(rerank='vision')
    with (
        patch(
            'server.apps.pipelines.stages.footage_search.search_candidates',
            new=AsyncMock(return_value=[_candidate('1')]),
        ),
        patch(
            'server.apps.pipelines.stages.footage_search._vision_rank',
            new=AsyncMock(side_effect=RuntimeError('vision down')),
        ),
        _patched_download(),
        patch(
            'server.apps.pipelines.stages.footage_search._record_credit',
            new=AsyncMock(),
        ),
    ):
        result = asyncio.run(FootageSearchStage().run(ctx))
    assert result['asset_id'] == 'asset-uuid'
    assert result['rerank_score'] is None


def test_vision_success_populates_the_rerank_score() -> None:
    """A successful vision pass reports the selected item's confidence."""
    ctx = _make_ctx(rerank='vision')
    ranked = [_candidate('1')]
    with (
        patch(
            'server.apps.pipelines.stages.footage_search.search_candidates',
            new=AsyncMock(return_value=ranked),
        ),
        patch(
            'server.apps.pipelines.stages.footage_search._vision_rank',
            new=AsyncMock(return_value=(ranked, {'1': 0.87})),
        ),
        _patched_download(),
        patch(
            'server.apps.pipelines.stages.footage_search._record_credit',
            new=AsyncMock(),
        ),
    ):
        result = asyncio.run(FootageSearchStage().run(ctx))
    assert result['rerank_score'] == pytest.approx(0.87)
