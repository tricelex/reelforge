"""Tests for ClipAnalyzeStage."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.clip_analyze import ClipAnalyzeStage


def test_clip_analyze_attributes() -> None:
    assert ClipAnalyzeStage.key == 'clip_analyze'
    assert ClipAnalyzeStage.queue == 'render'
    assert ClipAnalyzeStage.max_retries == 2
    assert ClipAnalyzeStage.timeout_s == 3600


def test_clip_analyze_fan_out_returns_none() -> None:
    assert ClipAnalyzeStage().fan_out(MagicMock()) is None


def test_clip_analyze_registered() -> None:
    from server.apps.pipelines.stages.base import STAGE_REGISTRY

    assert 'clip_analyze' in STAGE_REGISTRY


def test_clip_analyze_run() -> None:
    ctx = MagicMock()
    ctx.run.id = 'run-id'
    ctx.run.prompt_snapshot = {}
    ctx.upstream = {
        'clip_transcribe': {'manifest_asset_id': 'manifest-asset-id'},
    }
    ctx.config = {'clips_requested': 3}
    ctx.costs.record = AsyncMock()
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    ctx.prompts.get_raw_templates = AsyncMock(return_value=('', ''))
    ctx.prompts.get_model = AsyncMock(return_value=None)

    manifest = {
        'transcript_text': 'Hello world',
        'enriched_transcript': [
            {
                'word': 'Hello',
                'start': 0.0,
                'end': 0.5,
                'speaker_id': 'speaker_0',
            },
        ],
        'scene_cuts': [5.0],
        'source_duration_sec': 120.0,
    }

    fake_manifest_asset = MagicMock()
    fake_candidate = MagicMock()
    fake_candidate.id = 'candidate-uuid-1'

    async def _inner() -> dict:
        with (
            patch(
                'server.apps.assets.models.Asset',
            ) as mock_asset_cls,
            patch(
                'server.apps.clips.analysis.ClipAnalysisService',
            ) as mock_svc_cls,
            patch(
                'server.apps.pipelines.stages.clip_analyze.asyncio.to_thread',
                new=AsyncMock(
                    side_effect=[
                        json.dumps(manifest).encode(),  # manifest read
                        [fake_candidate],  # svc.analyze
                    ],
                ),
            ),
        ):
            mock_asset_cls.objects.aget = AsyncMock(
                return_value=fake_manifest_asset,
            )
            mock_svc_cls.return_value = MagicMock()
            return await ClipAnalyzeStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['candidate_count'] == 1
    assert 'candidate-uuid-1' in result['candidate_ids']
    ctx.costs.record.assert_called_once_with(
        provider='openai',
        operation='clip_analysis',
        units=1,
        unit_cost_usd=0.05,
    )


def test_clip_analyze_default_clips_requested() -> None:
    ctx = MagicMock()
    ctx.run.id = 'run-id'
    ctx.run.prompt_snapshot = {}
    ctx.upstream = {
        'clip_transcribe': {'manifest_asset_id': 'mid'},
    }
    ctx.config = {}
    ctx.costs.record = AsyncMock()
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    ctx.prompts.get_raw_templates = AsyncMock(return_value=('', ''))
    ctx.prompts.get_model = AsyncMock(return_value=None)

    manifest: dict = {
        'transcript_text': '',
        'enriched_transcript': [],
        'scene_cuts': [],
    }

    async def _inner() -> dict:
        with (
            patch(
                'server.apps.assets.models.Asset',
            ) as mock_asset_cls,
            patch(
                'server.apps.clips.analysis.ClipAnalysisService',
            ) as mock_svc_cls,
            patch(
                'server.apps.pipelines.stages.clip_analyze.asyncio.to_thread',
                new=AsyncMock(
                    side_effect=[
                        json.dumps(manifest).encode(),
                        [],
                    ],
                ),
            ),
        ):
            mock_asset_cls.objects.aget = AsyncMock(return_value=MagicMock())
            mock_svc_cls.return_value = MagicMock()
            return await ClipAnalyzeStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['candidate_count'] == 0
