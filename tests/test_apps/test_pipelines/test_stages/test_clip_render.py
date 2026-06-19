"""Tests for ClipRenderStage."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.clip_render import ClipRenderStage


def test_clip_render_attributes() -> None:
    assert ClipRenderStage.key == 'clip_render'
    assert ClipRenderStage.queue == 'render'
    assert ClipRenderStage.max_retries == 1
    assert ClipRenderStage.timeout_s == 3600


def test_clip_render_registered() -> None:
    from server.apps.pipelines.stages.base import STAGE_REGISTRY

    assert 'clip_render' in STAGE_REGISTRY


def test_clip_render_fan_out_returns_shards() -> None:
    ctx = MagicMock()
    ctx.upstream = {
        'clip_approval_gate': {
            'approved_candidate_ids': ['uuid-1', 'uuid-2'],
        },
    }
    shards = ClipRenderStage().fan_out(ctx)
    assert shards is not None
    assert len(shards) == 2
    assert shards[0] == {'candidate_id': 'uuid-1'}
    assert shards[1] == {'candidate_id': 'uuid-2'}


def test_clip_render_fan_out_empty_list() -> None:
    ctx = MagicMock()
    ctx.upstream = {'clip_approval_gate': {'approved_candidate_ids': []}}
    shards = ClipRenderStage().fan_out(ctx)
    assert shards == []


def test_clip_render_fan_out_missing_gate_key() -> None:
    ctx = MagicMock()
    ctx.upstream = {}
    shards = ClipRenderStage().fan_out(ctx)
    assert shards == []


def test_clip_render_run() -> None:
    ctx = MagicMock()
    ctx.execution.input_snapshot = {'candidate_id': 'cand-uuid'}
    ctx.upstream = {
        'clip_ingest': {'asset_id': 'src-asset-id'},
        'clip_transcribe': {'manifest_asset_id': 'manifest-asset-id'},
    }

    manifest = {'transcript_json': {'segments': []}}
    fake_rendered_bytes = b'rendered video'
    fake_render_asset = MagicMock()
    fake_render_asset.id = 'render-asset-uuid'

    fake_candidate = MagicMock()
    fake_candidate.start_sec = 10.0
    fake_candidate.end_sec = 70.0
    fake_candidate.hook_text = 'Watch this!'
    fake_candidate.layout_config = MagicMock()
    fake_candidate.style_config = MagicMock()
    fake_candidate.timed_overlays.all.return_value = _AsyncIter([])
    fake_candidate.asave = AsyncMock()

    fake_source_asset = MagicMock()
    fake_manifest_asset = MagicMock()

    async def _inner() -> dict:
        with (
            patch(
                'server.apps.clips.models.ClipCandidate',
            ) as mock_cand_cls,
            patch(
                'server.apps.assets.models.Asset',
            ) as mock_asset_cls,
            patch('server.apps.assets.models.AssetKind'),
            patch(
                'server.apps.rendering.clip_render_pipeline.ClipRenderPipeline',
            ) as mock_pipeline_cls,
            patch(
                'server.apps.rendering.clip_render_pipeline.PipelineRenderConfig',
            ),
            patch(
                'server.apps.pipelines.stages.clip_render.asyncio.to_thread',
                new=AsyncMock(
                    side_effect=[
                        b'video bytes',
                        json.dumps(manifest).encode(),
                        None,  # write_bytes
                        None,  # pipeline.run
                        fake_rendered_bytes,
                    ],
                ),
            ),
        ):
            cand_qs = MagicMock()
            cand_qs.select_related.return_value = cand_qs
            cand_qs.aget = AsyncMock(return_value=fake_candidate)
            mock_cand_cls.objects = cand_qs

            asset_qs = MagicMock()
            asset_qs.aget = AsyncMock(
                side_effect=[fake_source_asset, fake_manifest_asset],
            )
            mock_asset_cls.objects = asset_qs

            mock_pipeline_cls.return_value = MagicMock()
            ctx.assets.save = AsyncMock(return_value=fake_render_asset)

            return await ClipRenderStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['candidate_id'] == 'cand-uuid'
    assert result['asset_id'] == 'render-asset-uuid'
    fake_candidate.asave.assert_called_once()


class _AsyncIter:
    """Minimal async iterator helper for testing."""

    def __init__(self, items: list) -> None:
        self._items = iter(items)

    def __aiter__(self) -> '_AsyncIter':
        return self

    async def __anext__(self) -> object:
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration
