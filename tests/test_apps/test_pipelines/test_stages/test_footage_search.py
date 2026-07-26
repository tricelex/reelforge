"""Tests for the footage_search fan-out stage and its fallback cascade."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from server.apps.generation.clients.stock.base import FootageCandidate
from server.apps.pipelines.schemas import (
    CandidateRanking,
    CandidateRankingOutput,
)
from server.apps.pipelines.stages.footage_search import (
    FootageSearchStage,
    _download_and_validate,
    _fetch_bytes,
    _probe_ok,
    _record_credit_sync,
    _vision_rank,
)
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


def test_all_candidates_fail_download_broadens_to_next_query() -> None:
    """When every candidate in a query fails to validate, try the next query."""
    ctx = _make_ctx()
    search = AsyncMock(
        side_effect=[[_candidate('1'), _candidate('2')], [_candidate('3')]],
    )
    download = AsyncMock(side_effect=[None, None, (b'bytes', 'video/mp4')])
    with (
        patch(
            'server.apps.pipelines.stages.footage_search.search_candidates',
            new=search,
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
    assert search.await_count == 2
    assert download.await_count == 3
    assert result['asset_id'] == 'asset-uuid'


def test_rank_with_metadata_mode_uses_metadata_heuristic() -> None:
    """rerank_mode='metadata' orders candidates by the metadata heuristic."""
    ctx = _make_ctx()
    config = MagicMock()
    config.rerank_mode = 'metadata'
    snap = {'visual_concept': 'ocean waves', 'negative_terms': []}
    matching = FootageCandidate(
        provider='pexels',
        external_id='match',
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
        title='ocean waves crashing',
        tags=(),
    )
    non_matching = _candidate('no-match')

    ranked, scores = asyncio.run(
        FootageSearchStage()._rank(
            ctx,
            [non_matching, matching],
            snap,
            config,
        ),
    )
    assert scores == {}
    assert ranked[0].external_id == 'match'


# ---------------------------------------------------------------------------
# _fetch_bytes — I/O boundary is httpx.AsyncClient
# ---------------------------------------------------------------------------


def test_fetch_bytes_returns_response_content() -> None:
    """_fetch_bytes returns the response body on a successful GET."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.content = b'the-bytes'
    mock_resp.raise_for_status = MagicMock()

    async def _run() -> bytes:
        with patch(
            'httpx.AsyncClient.get',
            new=AsyncMock(return_value=mock_resp),
        ):
            return await _fetch_bytes('https://e.test/v.mp4')

    assert asyncio.run(_run()) == b'the-bytes'


def test_fetch_bytes_raises_on_http_error_status() -> None:
    """_fetch_bytes propagates raise_for_status() errors to the caller."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            'not found',
            request=MagicMock(),
            response=MagicMock(status_code=404),
        ),
    )

    async def _run() -> bytes:
        with patch(
            'httpx.AsyncClient.get',
            new=AsyncMock(return_value=mock_resp),
        ):
            return await _fetch_bytes('https://e.test/missing.mp4')

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# _probe_ok — I/O boundary is async_ffprobe
# ---------------------------------------------------------------------------


def test_probe_ok_true_when_probe_reports_streams() -> None:
    """A probe with streams present validates the download."""

    async def _run() -> bool:
        with patch(
            'server.apps.rendering.ffmpeg.async_ffprobe',
            new=AsyncMock(return_value={'streams': [{'codec_type': 'video'}]}),
        ):
            return await _probe_ok(b'fake-mp4-bytes', '.mp4')

    assert asyncio.run(_run()) is True


def test_probe_ok_false_when_probe_has_no_streams_or_format() -> None:
    """An empty probe result is treated as unusable media."""

    async def _run() -> bool:
        with patch(
            'server.apps.rendering.ffmpeg.async_ffprobe',
            new=AsyncMock(return_value={'streams': [], 'format': {}}),
        ):
            return await _probe_ok(b'garbage', '.jpg')

    assert asyncio.run(_run()) is False


def test_probe_ok_false_when_ffprobe_raises() -> None:
    """A crashing ffprobe call degrades to False instead of raising."""

    async def _run() -> bool:
        with patch(
            'server.apps.rendering.ffmpeg.async_ffprobe',
            new=AsyncMock(side_effect=RuntimeError('ffprobe exploded')),
        ):
            return await _probe_ok(b'garbage', '.mp4')

    assert asyncio.run(_run()) is False


# ---------------------------------------------------------------------------
# _download_and_validate — composes _fetch_bytes + _probe_ok
# ---------------------------------------------------------------------------


def test_download_and_validate_returns_content_and_mime_for_video() -> None:
    """A successful download+probe returns (bytes, video mime)."""
    candidate = _candidate('1')

    async def _run() -> tuple[bytes, str] | None:
        with (
            patch(
                'server.apps.pipelines.stages.footage_search._fetch_bytes',
                new=AsyncMock(return_value=b'video-bytes'),
            ),
            patch(
                'server.apps.pipelines.stages.footage_search._probe_ok',
                new=AsyncMock(return_value=True),
            ),
        ):
            return await _download_and_validate(candidate)

    result = asyncio.run(_run())
    assert result == (b'video-bytes', 'video/mp4')


def test_download_and_validate_returns_image_mime_for_stills() -> None:
    """Image candidates validate to image/jpeg."""
    candidate = FootageCandidate(
        provider='pexels',
        external_id='img-1',
        media_type='image',
        download_url='https://e.test/i.jpg',
        thumb_url='https://e.test/t.jpg',
        source_page_url='https://e.test/p',
        width=1920,
        height=1080,
        duration_s=None,
        license='pexels',
        license_url='',
        author='A',
        attribution_required=False,
        title='cliff',
        tags=(),
    )

    async def _run() -> tuple[bytes, str] | None:
        with (
            patch(
                'server.apps.pipelines.stages.footage_search._fetch_bytes',
                new=AsyncMock(return_value=b'jpeg-bytes'),
            ),
            patch(
                'server.apps.pipelines.stages.footage_search._probe_ok',
                new=AsyncMock(return_value=True),
            ),
        ):
            return await _download_and_validate(candidate)

    result = asyncio.run(_run())
    assert result == (b'jpeg-bytes', 'image/jpeg')


def test_download_and_validate_returns_none_on_fetch_http_error() -> None:
    """A download transport error is swallowed and reported as unusable."""
    candidate = _candidate('1')

    async def _run() -> tuple[bytes, str] | None:
        with patch(
            'server.apps.pipelines.stages.footage_search._fetch_bytes',
            new=AsyncMock(side_effect=httpx.ConnectError('boom')),
        ):
            return await _download_and_validate(candidate)

    assert asyncio.run(_run()) is None


def test_download_and_validate_returns_none_on_empty_content() -> None:
    """Zero-byte downloads are treated as unusable without probing."""
    candidate = _candidate('1')
    probe_mock = AsyncMock(return_value=True)

    async def _run() -> tuple[bytes, str] | None:
        with (
            patch(
                'server.apps.pipelines.stages.footage_search._fetch_bytes',
                new=AsyncMock(return_value=b''),
            ),
            patch(
                'server.apps.pipelines.stages.footage_search._probe_ok',
                new=probe_mock,
            ),
        ):
            return await _download_and_validate(candidate)

    result = asyncio.run(_run())
    probe_mock.assert_not_called()
    assert result is None


def test_download_and_validate_returns_none_on_probe_failure() -> None:
    """A downloaded file that fails ffprobe validation is unusable."""
    candidate = _candidate('1')

    async def _run() -> tuple[bytes, str] | None:
        with (
            patch(
                'server.apps.pipelines.stages.footage_search._fetch_bytes',
                new=AsyncMock(return_value=b'corrupt'),
            ),
            patch(
                'server.apps.pipelines.stages.footage_search._probe_ok',
                new=AsyncMock(return_value=False),
            ),
        ):
            return await _download_and_validate(candidate)

    assert asyncio.run(_run()) is None


# ---------------------------------------------------------------------------
# _record_credit_sync — real DB write
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_record_credit_sync_persists_a_footage_credit_row() -> None:
    """The real ORM write creates a FootageCredit tied to the asset+run."""
    from django.core.files.base import ContentFile

    from server.apps.assets.models import Asset, AssetKind, FootageCredit
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
    )

    channel = Channel.objects.create(
        name='Footage Credit Ch',
        kind=ChannelKind.LONGFORM,
    )
    blueprint = PipelineBlueprint.objects.create(
        name='footage_credit_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='test',
    )
    asset = Asset(kind=AssetKind.FOOTAGE, mime='video/mp4', checksum='abc')
    asset.file.save('clip.mp4', ContentFile(b'x'), save=False)
    asset.save()

    _record_credit_sync(str(run.id), str(asset.id), 2, _candidate('9'))

    credit = FootageCredit.objects.get(asset_id=asset.id)
    assert credit.run_id == run.id
    assert credit.scene_idx == 2
    assert credit.provider == 'pexels'
    assert credit.title == 'ocean'


# ---------------------------------------------------------------------------
# _vision_rank — real body, mocked model resolution + LLM call
# ---------------------------------------------------------------------------


def test_vision_rank_builds_content_and_applies_llm_scores() -> None:
    """_vision_rank sends one prompt entry per candidate and applies scores."""
    ctx = _make_ctx(rerank='vision')
    candidates = [_candidate('1'), _candidate('2')]
    llm_output = CandidateRankingOutput(
        rankings=[
            CandidateRanking(external_id='2', score=0.9),
            CandidateRanking(external_id='1', score=0.1),
        ],
    )
    run_agent_mock = AsyncMock(return_value=llm_output)

    async def _run() -> tuple[list[FootageCandidate], dict[str, float]]:
        with (
            patch(
                'server.apps.generation.logic.stage_model.resolve_stage_model',
                new=AsyncMock(return_value='gpt-4o-mini'),
            ),
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=run_agent_mock,
            ),
        ):
            return await _vision_rank(ctx, candidates, 'ocean waves')

    ranked, scores = asyncio.run(_run())
    assert scores == {'2': 0.9, '1': 0.1}
    assert [c.external_id for c in ranked] == ['2', '1']
    run_agent_mock.assert_awaited_once()
    call_kwargs = run_agent_mock.await_args.kwargs
    assert call_kwargs['stage_key'] == 'footage_search'
    assert call_kwargs['model_slug'] == 'gpt-4o-mini'
    prompt_content = run_agent_mock.await_args.args[1]
    assert 'ocean waves' in prompt_content[0]
    assert 'external_id=1' in prompt_content
