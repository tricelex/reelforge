"""Tests for pipeline-level scheduled tasks."""

import asyncio
from collections.abc import Coroutine
from datetime import timedelta
from typing import Any

import django.utils.timezone as tz
import pytest


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


@pytest.mark.django_db(transaction=True)
def test_swap_underperforming_thumbnails_swaps_below_median_ctr() -> None:
    """A job with below-median CTR and an untested candidate gets swapped once."""
    from unittest.mock import AsyncMock, patch

    from server.apps.analytics.models import PublishJobMetric
    from server.apps.channels.models import (
        Channel,
        ChannelKind,
        YouTubeCredential,
    )
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.tasks import swap_underperforming_thumbnails
    from server.apps.publishing.models import PublishJob, PublishStatus

    channel = Channel.objects.create(name='Swap Ch', kind=ChannelKind.LONGFORM)
    YouTubeCredential.objects.create(
        channel=channel,
        access_token='tok',
        refresh_token='rtok',
    )
    bp = PipelineBlueprint.objects.create(
        name='swap_test_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )

    # A healthy prior job establishes the channel's median CTR at 0.06.
    good_run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={},
        topic='good',
    )
    good_job = PublishJob.objects.create(
        run=good_run,
        channel=channel,
        status=PublishStatus.COMPLETED,
        youtube_video_id='yt_good',
    )
    PublishJob.objects.filter(id=good_job.id).update(
        created_at=tz.now() - timedelta(days=10),
    )
    PublishJobMetric.objects.create(
        publish_job=good_job,
        views=1000,
        impressions_ctr=0.06,
    )

    # The job under test: below-median CTR, 24-48h old, has an untested candidate.
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={},
        topic='under',
    )
    StageExecution.objects.create(
        run=run,
        stage_key='thumbnail',
        status=StageStatus.SUCCEEDED,
        input_hash='',
        output={
            'candidates': [
                {'rank': 0, 'asset_id': 'thumb-0'},
                {'rank': 1, 'asset_id': 'thumb-1'},
            ],
        },
    )
    job = PublishJob.objects.create(
        run=run,
        channel=channel,
        status=PublishStatus.COMPLETED,
        youtube_video_id='yt_under',
        thumbnail_asset_id='thumb-0',
    )
    PublishJob.objects.filter(id=job.id).update(
        created_at=tz.now() - timedelta(hours=30),
    )
    PublishJobMetric.objects.create(
        publish_job=job,
        views=500,
        impressions_ctr=0.02,
    )

    async def _inner() -> None:
        with (
            patch(
                'server.apps.pipelines.tasks.yt_client.refresh_token_if_needed',
                new=AsyncMock(return_value='fresh_tok'),
            ),
            patch(
                'server.apps.pipelines.tasks.yt_client.set_thumbnail',
                new=AsyncMock(),
            ) as mock_set_thumb,
            patch(
                'server.apps.pipelines.tasks._download_thumbnail_bytes',
                new=AsyncMock(return_value=b'thumb bytes'),
            ),
        ):
            await swap_underperforming_thumbnails()
            mock_set_thumb.assert_awaited_once_with(
                'fresh_tok',
                'yt_under',
                b'thumb bytes',
            )

    _run(_inner())

    job.refresh_from_db()
    assert job.thumbnail_asset_id == 'thumb-1'
    assert job.thumbnail_tested is True
    assert job.tested_candidate_ranks == [1]


def _make_channel_with_jobs() -> tuple[Any, Any, Any]:
    """Create a channel + blueprint and return (channel, blueprint, run)."""
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
    )

    channel = Channel.objects.create(name='Med Ch', kind=ChannelKind.LONGFORM)
    bp = PipelineBlueprint.objects.create(
        name='med_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={},
        topic='t',
    )
    return channel, bp, run


@pytest.mark.django_db
def test_channel_median_ctr_none_and_even_average() -> None:
    """Median returns None with no data and averages an even-sized sample."""
    import uuid

    from server.apps.analytics.models import PublishJobMetric
    from server.apps.pipelines.models import PipelineRun
    from server.apps.pipelines.tasks import _channel_median_ctr
    from server.apps.publishing.models import PublishJob, PublishStatus

    channel, bp, _run_obj = _make_channel_with_jobs()

    assert _channel_median_ctr(channel.id, uuid.uuid4()) is None

    for ctr in (0.04, 0.06):
        run = PipelineRun.objects.create(
            channel=channel,
            blueprint=bp,
            blueprint_snapshot={},
            topic='t',
        )
        pj = PublishJob.objects.create(
            run=run,
            channel=channel,
            status=PublishStatus.COMPLETED,
            youtube_video_id=f'yt_{ctr}',
        )
        PublishJobMetric.objects.create(publish_job=pj, impressions_ctr=ctr)

    assert _channel_median_ctr(channel.id, uuid.uuid4()) == pytest.approx(0.05)


@pytest.mark.django_db(transaction=True)
def test_maybe_swap_job_skips_when_no_metric() -> None:
    """A job without a CTR metric is skipped (no swap, no state change)."""
    from server.apps.pipelines.tasks import _maybe_swap_job
    from server.apps.publishing.models import PublishJob, PublishStatus

    channel, _bp, run = _make_channel_with_jobs()
    job = PublishJob.objects.create(
        run=run,
        channel=channel,
        status=PublishStatus.COMPLETED,
        youtube_video_id='yt_nometric',
    )

    _run(_maybe_swap_job(job))

    job.refresh_from_db()
    assert job.thumbnail_tested is False


@pytest.mark.django_db(transaction=True)
def test_maybe_swap_job_skips_when_at_or_above_median() -> None:
    """A job at/above the channel median CTR is not swapped."""
    from server.apps.analytics.models import PublishJobMetric
    from server.apps.pipelines.models import PipelineRun
    from server.apps.pipelines.tasks import _maybe_swap_job
    from server.apps.publishing.models import PublishJob, PublishStatus

    channel, bp, run = _make_channel_with_jobs()

    other_run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={},
        topic='o',
    )
    other = PublishJob.objects.create(
        run=other_run,
        channel=channel,
        status=PublishStatus.COMPLETED,
        youtube_video_id='yt_other',
    )
    PublishJobMetric.objects.create(publish_job=other, impressions_ctr=0.04)

    job = PublishJob.objects.create(
        run=run,
        channel=channel,
        status=PublishStatus.COMPLETED,
        youtube_video_id='yt_high',
    )
    PublishJobMetric.objects.create(publish_job=job, impressions_ctr=0.09)

    _run(_maybe_swap_job(job))

    job.refresh_from_db()
    assert job.thumbnail_tested is False


@pytest.mark.django_db(transaction=True)
def test_maybe_swap_job_marks_tested_when_candidates_exhausted() -> None:
    """Below-median job with no untested candidate is marked tested, not swapped."""
    from server.apps.analytics.models import PublishJobMetric
    from server.apps.pipelines.models import (
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.tasks import _maybe_swap_job
    from server.apps.publishing.models import PublishJob, PublishStatus

    channel, bp, run = _make_channel_with_jobs()

    other_run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={},
        topic='o',
    )
    other = PublishJob.objects.create(
        run=other_run,
        channel=channel,
        status=PublishStatus.COMPLETED,
        youtube_video_id='yt_other',
    )
    PublishJobMetric.objects.create(publish_job=other, impressions_ctr=0.09)

    StageExecution.objects.create(
        run=run,
        stage_key='thumbnail',
        status=StageStatus.SUCCEEDED,
        input_hash='',
        output={'candidates': [{'rank': 0, 'asset_id': 'only'}]},
    )
    job = PublishJob.objects.create(
        run=run,
        channel=channel,
        status=PublishStatus.COMPLETED,
        youtube_video_id='yt_low',
        thumbnail_asset_id='only',
    )
    PublishJobMetric.objects.create(publish_job=job, impressions_ctr=0.01)

    _run(_maybe_swap_job(job))

    job.refresh_from_db()
    assert job.thumbnail_tested is True
    assert job.thumbnail_asset_id == 'only'


@pytest.mark.django_db(transaction=True)
def test_next_untested_candidate_returns_none_without_stage() -> None:
    """No thumbnail StageExecution means there is nothing to swap to."""
    from server.apps.pipelines.tasks import _next_untested_candidate
    from server.apps.publishing.models import PublishJob, PublishStatus

    channel, _bp, run = _make_channel_with_jobs()
    job = PublishJob.objects.create(
        run=run,
        channel=channel,
        status=PublishStatus.COMPLETED,
        youtube_video_id='yt_nostage',
    )

    result = _run(_next_untested_candidate(job))
    assert result is None


@pytest.mark.django_db(transaction=True)
def test_apply_thumbnail_swap_skips_without_credential() -> None:
    """A channel with no YouTubeCredential silently skips the swap."""
    from server.apps.pipelines.tasks import _apply_thumbnail_swap
    from server.apps.publishing.models import PublishJob, PublishStatus

    channel, _bp, run = _make_channel_with_jobs()
    job = PublishJob.objects.create(
        run=run,
        channel=channel,
        status=PublishStatus.COMPLETED,
        youtube_video_id='yt_nocred',
        thumbnail_asset_id='a',
    )

    _run(_apply_thumbnail_swap(job, {'rank': 1, 'asset_id': 'b'}))

    job.refresh_from_db()
    assert job.thumbnail_asset_id == 'a'
