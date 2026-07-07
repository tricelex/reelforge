"""Tests for analytics refresh task."""

import asyncio
from collections.abc import Coroutine
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from server.apps.analytics.tasks import refresh_analytics_views


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    from asgiref.sync import sync_to_async

    @sync_to_async
    def _close_connections() -> None:
        from django.db import connections

        connections.close_all()

    async def _wrapped() -> Any:
        try:
            return await coro
        finally:
            await _close_connections()

    return asyncio.run(_wrapped())


def test_refresh_analytics_views_executes_refresh_sql() -> None:
    """refresh_analytics_views runs REFRESH MATERIALIZED VIEW for all views."""
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_connection = MagicMock()
    mock_connection.cursor.return_value = mock_cursor

    async def _inner() -> None:
        with patch('django.db.connection', mock_connection):
            await refresh_analytics_views()

    asyncio.run(_inner())

    calls = [str(c) for c in mock_cursor.execute.call_args_list]
    assert any('analytics_run_cost_summary' in c for c in calls)
    assert any('analytics_channel_roi' in c for c in calls)
    assert any('analytics_stage_performance' in c for c in calls)


@pytest.mark.django_db(transaction=True)
def test_pull_publish_job_metrics_writes_metric_rows() -> None:
    """pull_publish_job_metrics fetches a report per recent COMPLETED PublishJob."""
    from unittest.mock import AsyncMock, patch

    from server.apps.analytics.models import PublishJobMetric
    from server.apps.analytics.tasks import pull_publish_job_metrics
    from server.apps.channels.models import (
        Channel,
        ChannelKind,
        YouTubeCredential,
    )
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
    )
    from server.apps.publishing.models import PublishJob, PublishStatus

    channel = Channel.objects.create(
        name='Metrics Ch',
        kind=ChannelKind.LONGFORM,
    )
    YouTubeCredential.objects.create(
        channel=channel,
        access_token='tok',
        refresh_token='rtok',
    )
    bp = PipelineBlueprint.objects.create(
        name='metrics_test_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={},
        topic='t',
    )
    job = PublishJob.objects.create(
        run=run,
        channel=channel,
        status=PublishStatus.COMPLETED,
        youtube_video_id='yt_vid_1',
    )
    # A second job on the SAME channel exercises the channel-ID cache.
    run2 = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={},
        topic='t2',
    )
    job2 = PublishJob.objects.create(
        run=run2,
        channel=channel,
        status=PublishStatus.COMPLETED,
        youtube_video_id='yt_vid_2',
    )

    fake_report = {
        'views': 500,
        'avg_view_duration_s': 120.0,
        'avg_view_percentage': 45.0,
        'retention_curve': [
            {
                'elapsed_ratio': 0.1,
                'watch_ratio': 0.9,
                'relative_performance': 0.5,
            },
        ],
        'impressions': 8000,
        'impressions_ctr': 0.0625,
    }

    mock_channel_id = AsyncMock(return_value='UC123')

    async def _inner() -> None:
        with (
            patch(
                'server.apps.analytics.tasks.yt_client.refresh_token_if_needed',
                new=AsyncMock(return_value='fresh_tok'),
            ),
            patch(
                'server.apps.analytics.tasks.fetch_video_report',
                new=AsyncMock(return_value=fake_report),
            ),
            patch(
                'server.apps.analytics.tasks._get_channel_youtube_id',
                new=mock_channel_id,
            ),
        ):
            await pull_publish_job_metrics()

    _run(_inner())

    metric = PublishJobMetric.objects.get(publish_job=job)
    assert metric.views == 500
    assert metric.avg_view_percentage == 45.0
    assert metric.retention_curve[0]['watch_ratio'] == 0.9
    assert metric.impressions == 8000
    assert metric.impressions_ctr == 0.0625
    assert PublishJobMetric.objects.filter(publish_job=job2).exists()
    # Both jobs share a channel -> the channel-ID is resolved only once.
    assert mock_channel_id.await_count == 1


@pytest.mark.django_db(transaction=True)
def test_pull_publish_job_metrics_skips_jobs_without_credential() -> None:
    """A completed job whose channel has no credential is skipped, not written."""
    from server.apps.analytics.models import PublishJobMetric
    from server.apps.analytics.tasks import pull_publish_job_metrics
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
    )
    from server.apps.publishing.models import PublishJob, PublishStatus

    channel = Channel.objects.create(
        name='No Cred Ch',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='no_cred_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={},
        topic='t',
    )
    job = PublishJob.objects.create(
        run=run,
        channel=channel,
        status=PublishStatus.COMPLETED,
        youtube_video_id='yt_no_cred',
    )

    _run(pull_publish_job_metrics())

    assert not PublishJobMetric.objects.filter(publish_job=job).exists()
