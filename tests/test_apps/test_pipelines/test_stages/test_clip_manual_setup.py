"""Tests for ClipManualSetupStage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.clip_manual_setup import ClipManualSetupStage


def test_clip_manual_setup_attributes() -> None:
    assert ClipManualSetupStage.key == 'clip_manual_setup'
    assert ClipManualSetupStage.queue == 'render'
    assert ClipManualSetupStage.max_retries == 1
    assert ClipManualSetupStage.timeout_s == 300


def test_clip_manual_setup_fan_out_returns_none() -> None:
    assert ClipManualSetupStage().fan_out(MagicMock()) is None


def test_clip_manual_setup_registered() -> None:
    from server.apps.pipelines.stages.base import STAGE_REGISTRY

    assert 'clip_manual_setup' in STAGE_REGISTRY


def test_clip_manual_setup_run_uses_ingest_duration() -> None:
    """When clip_ingest provides duration, no ffprobe call is made."""
    ctx = MagicMock()
    ctx.run = MagicMock()
    ctx.upstream = {
        'clip_ingest': {
            'asset_id': 'asset-uuid',
            'source_title': 'My Podcast',
            'source_duration_sec': 300.0,
        },
    }

    fake_candidate = MagicMock()
    fake_candidate.id = 'cand-uuid-1'

    async def _inner() -> dict:
        with patch(
            'server.apps.clips.models.ClipCandidate',
        ) as mock_candidate_cls:
            mock_candidate_cls.objects.acreate = AsyncMock(
                return_value=fake_candidate,
            )
            return await ClipManualSetupStage().run(ctx)

    result = asyncio.run(_inner())

    assert result == {'candidate_ids': ['cand-uuid-1'], 'candidate_count': 1}


def test_clip_manual_setup_run_probes_duration_when_zero() -> None:
    """When source_duration_sec is 0.0, ffprobe is called to determine it."""
    ctx = MagicMock()
    ctx.run = MagicMock()
    ctx.upstream = {
        'clip_ingest': {
            'asset_id': 'asset-uuid',
            'source_title': 'Uploaded Clip',
            'source_duration_sec': 0.0,
        },
    }

    fake_candidate = MagicMock()
    fake_candidate.id = 'cand-uuid-2'
    probe_result = {'format': {'duration': '120.5'}}

    async def _inner() -> dict:
        with (
            patch(
                'server.apps.assets.models.Asset',
            ) as mock_asset_cls,
            patch(
                'server.apps.pipelines.stages.clip_manual_setup.asyncio.to_thread',
                new=AsyncMock(
                    side_effect=[
                        b'video bytes',  # asset.file.read
                        None,  # video_path.write_bytes
                    ],
                ),
            ),
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(return_value=probe_result),
            ),
            patch(
                'server.apps.clips.models.ClipCandidate',
            ) as mock_candidate_cls,
        ):
            mock_asset_cls.objects.aget = AsyncMock(return_value=MagicMock())
            mock_candidate_cls.objects.acreate = AsyncMock(
                return_value=fake_candidate,
            )
            return await ClipManualSetupStage().run(ctx)

    result = asyncio.run(_inner())

    assert result == {'candidate_ids': ['cand-uuid-2'], 'candidate_count': 1}


def test_clip_manual_setup_run_falls_back_title() -> None:
    """When source_title is empty, candidate title falls back to 'Full Video'."""
    from server.apps.clips.logic.constants import CandidateStatus

    ctx = MagicMock()
    ctx.run = MagicMock()
    ctx.upstream = {
        'clip_ingest': {
            'asset_id': 'asset-uuid',
            'source_title': '',
            'source_duration_sec': 60.0,
        },
    }

    fake_candidate = MagicMock()
    fake_candidate.id = 'cand-uuid-3'

    async def _inner() -> None:
        with patch(
            'server.apps.clips.models.ClipCandidate',
        ) as mock_cls:
            mock_cls.objects.acreate = AsyncMock(return_value=fake_candidate)
            await ClipManualSetupStage().run(ctx)
            mock_cls.objects.acreate.assert_awaited_once_with(
                run=ctx.run,
                start_sec=0.0,
                end_sec=60.0,
                title='Full Video',
                is_manual=True,
                status=CandidateStatus.PROPOSED,
            )

    asyncio.run(_inner())
