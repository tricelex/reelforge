"""Tests for the publish pipeline stage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.pipelines.stages.publish import PublishStage, _download_asset


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.channel.id = 'chan-1'
    ctx.run.id = 'run-1'
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.upstream = {
        'metadata': {
            'title': 'Test Video',
            'description': 'A description',
            'tags': ['test', 'video'],
            'category': 'Education',
        },
        'assembly': {'asset_id': 'asset-final'},
        'review_gate': {
            'thumbnail_asset_id': 'asset-thumb',
            'schedule_at': None,
        },
    }
    return ctx


def test_publish_stage_key() -> None:
    assert PublishStage.key == 'publish'
    assert PublishStage.queue == 'api'


def test_publish_stage_fan_out_none() -> None:
    assert PublishStage().fan_out(MagicMock()) is None


def test_publish_run_creates_publish_job() -> None:
    ctx = _make_ctx()

    fake_credential = MagicMock()
    fake_credential.token_expiry = None

    fake_job = MagicMock(id='job-1')
    fake_job.asave = AsyncMock()

    async def _inner() -> dict:
        with (
            patch(
                'server.apps.pipelines.stages.publish.YouTubeCredential'
                '.objects.aget',
                new=AsyncMock(return_value=fake_credential),
            ),
            patch(
                'server.apps.pipelines.stages.publish.yt_client'
                '.refresh_token_if_needed',
                new=AsyncMock(return_value='access_token'),
            ),
            patch(
                'server.apps.pipelines.stages.publish._download_asset',
                new=AsyncMock(return_value=b'video bytes'),
            ),
            patch(
                'server.apps.pipelines.stages.publish.yt_client.upload_video',
                new=AsyncMock(return_value='yt_abc123'),
            ),
            patch(
                'server.apps.pipelines.stages.publish.yt_client.set_thumbnail',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.pipelines.stages.publish.PublishJob.objects.acreate',
                new=AsyncMock(return_value=fake_job),
            ),
            patch(
                'server.apps.pipelines.stages.publish.Asset.objects.aget',
                new=AsyncMock(return_value=MagicMock()),
            ),
        ):
            return await PublishStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['youtube_video_id'] == 'yt_abc123'
    assert 'publish_job_id' in result


def test_publish_run_no_thumbnail_when_not_selected() -> None:
    """When review_gate provides no thumbnail_asset_id, set_thumbnail is not called."""
    ctx = _make_ctx()
    ctx.upstream['review_gate']['thumbnail_asset_id'] = None

    fake_job = MagicMock(id='job-2')
    fake_job.asave = AsyncMock()

    async def _inner() -> dict:
        with (
            patch(
                'server.apps.pipelines.stages.publish.YouTubeCredential'
                '.objects.aget',
                new=AsyncMock(return_value=MagicMock(token_expiry=None)),
            ),
            patch(
                'server.apps.pipelines.stages.publish.yt_client'
                '.refresh_token_if_needed',
                new=AsyncMock(return_value='tok'),
            ),
            patch(
                'server.apps.pipelines.stages.publish._download_asset',
                new=AsyncMock(return_value=b'video'),
            ),
            patch(
                'server.apps.pipelines.stages.publish.yt_client.upload_video',
                new=AsyncMock(return_value='yt_def456'),
            ),
            patch(
                'server.apps.pipelines.stages.publish.yt_client.set_thumbnail',
                new=AsyncMock(),
            ) as mock_set_thumb,
            patch(
                'server.apps.pipelines.stages.publish.PublishJob.objects.acreate',
                new=AsyncMock(return_value=fake_job),
            ),
            patch(
                'server.apps.pipelines.stages.publish.Asset.objects.aget',
                new=AsyncMock(return_value=MagicMock()),
            ),
        ):
            result = await PublishStage().run(ctx)
            mock_set_thumb.assert_not_called()
            return result

    result = asyncio.run(_inner())
    assert result['youtube_video_id'] == 'yt_def456'
