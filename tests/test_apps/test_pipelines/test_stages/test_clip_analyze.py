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
    ctx.upstream = {
        'clip_transcribe': {'manifest_asset_id': 'manifest-asset-id'},
        'clip_ingest': {'asset_id': 'source-asset-id'},
    }
    ctx.config = {'clips_requested': 3}
    ctx.costs.record = AsyncMock()

    manifest = {
        'transcript_text': 'Hello world',
        'enriched_transcript': [
            {'word': 'Hello', 'start': 0.0, 'end': 0.5, 'speaker_id': 'UNKNOWN'},
        ],
        'scene_cuts': [5.0],
        'source_duration_sec': 120.0,
    }

    fake_manifest_asset = MagicMock()
    fake_source_asset = MagicMock()
    fake_candidate = MagicMock()
    fake_candidate.id = 'candidate-uuid-1'
    diar_segments = [{'speaker_id': 'SPEAKER_A', 'start': 0.0, 'end': 2.0}]

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
                        b'video bytes',  # source read
                        None,  # write_bytes
                        diar_segments,  # diarize
                        None,  # manifest update
                        [fake_candidate],  # svc.analyze
                    ],
                ),
            ),
        ):
            mock_asset_cls.objects.aget = AsyncMock(
                side_effect=[fake_manifest_asset, fake_source_asset],
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


def test_clip_analyze_fails_when_diarize_fails() -> None:
    ctx = MagicMock()
    ctx.run.id = 'run-id'
    ctx.upstream = {
        'clip_transcribe': {'manifest_asset_id': 'manifest-asset-id'},
        'clip_ingest': {'asset_id': 'source-asset-id'},
    }
    ctx.config = {}
    ctx.costs.record = AsyncMock()

    manifest: dict = {
        'transcript_text': '',
        'enriched_transcript': [],
        'scene_cuts': [],
    }

    async def _inner() -> None:
        with (
            patch(
                'server.apps.assets.models.Asset',
            ) as mock_asset_cls,
            patch(
                'server.apps.pipelines.stages.clip_analyze.asyncio.to_thread',
                new=AsyncMock(
                    side_effect=[
                        json.dumps(manifest).encode(),
                        b'video bytes',
                        None,
                        RuntimeError('pyannote failed'),
                    ],
                ),
            ),
        ):
            mock_asset_cls.objects.aget = AsyncMock(
                side_effect=[MagicMock(), MagicMock()],
            )
            await ClipAnalyzeStage().run(ctx)

    try:
        asyncio.run(_inner())
        raise AssertionError('expected FatalProviderError')
    except Exception as exc:
        from server.common.exceptions import FatalProviderError

        assert isinstance(exc, FatalProviderError)
        assert 'diarization' in str(exc).lower() or 'pyannote' in str(exc).lower()


def test_clip_analyze_default_clips_requested() -> None:
    ctx = MagicMock()
    ctx.run.id = 'run-id'
    ctx.upstream = {
        'clip_transcribe': {'manifest_asset_id': 'mid'},
        'clip_ingest': {'asset_id': 'source-id'},
    }
    ctx.config = {}
    ctx.costs.record = AsyncMock()

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
                        b'video bytes',
                        None,
                        [],
                        None,
                        [],
                    ],
                ),
            ),
        ):
            mock_asset_cls.objects.aget = AsyncMock(
                side_effect=[MagicMock(), MagicMock()],
            )
            mock_svc_cls.return_value = MagicMock()
            return await ClipAnalyzeStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['candidate_count'] == 0
