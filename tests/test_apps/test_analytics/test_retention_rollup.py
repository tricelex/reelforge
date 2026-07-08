"""Tests for retention-curve aggregation by chapter retention device."""

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest

from server.apps.analytics.retention_rollup import (
    _bucket_curve_by_device,
    _chapter_boundaries_from_outline,
    compute_soft_spots,
)


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


def test_bucket_curve_by_device_maps_elapsed_ratio_to_chapter_device() -> None:
    """A curve point's elapsed_ratio*duration falls within a chapter's span."""
    retention_curve = [
        {'elapsed_ratio': 0.1, 'watch_ratio': 0.9, 'relative_performance': 0.6},
        {'elapsed_ratio': 0.6, 'watch_ratio': 0.4, 'relative_performance': 0.3},
    ]
    chapter_boundaries = [
        {'device': 'open_loop', 'start_s': 0.0, 'end_s': 30.0},
        {'device': 'tension_build', 'start_s': 30.0, 'end_s': 100.0},
    ]

    buckets = _bucket_curve_by_device(
        retention_curve,
        chapter_boundaries,
        total_duration_s=100.0,
    )

    assert buckets['open_loop'] == [0.6]
    assert buckets['tension_build'] == [0.3]


def test_bucket_curve_by_device_skips_points_outside_any_chapter() -> None:
    retention_curve = [
        {
            'elapsed_ratio': 0.99,
            'watch_ratio': 0.1,
            'relative_performance': 0.2,
        },
    ]
    chapter_boundaries = [
        {'device': 'open_loop', 'start_s': 0.0, 'end_s': 10.0},
    ]

    buckets = _bucket_curve_by_device(
        retention_curve,
        chapter_boundaries,
        total_duration_s=100.0,
    )
    assert buckets == {}


def test_bucket_curve_by_device_zero_duration_returns_empty() -> None:
    buckets = _bucket_curve_by_device(
        [
            {
                'elapsed_ratio': 0.5,
                'watch_ratio': 0.5,
                'relative_performance': 0.5,
            },
        ],
        [{'device': 'open_loop', 'start_s': 0.0, 'end_s': 10.0}],
        total_duration_s=0.0,
    )
    assert buckets == {}


def test_chapter_boundaries_from_outline_builds_cumulative_spans() -> None:
    chapters = [
        {'device': 'open_loop', 'target_seconds': 30},
        {'device': 'tension_build', 'target_seconds': 70},
    ]
    boundaries = _chapter_boundaries_from_outline(chapters)
    assert boundaries[0] == {
        'device': 'open_loop',
        'start_s': 0.0,
        'end_s': 30.0,
    }
    assert boundaries[1] == {
        'device': 'tension_build',
        'start_s': 30.0,
        'end_s': 100.0,
    }


def _seed_run_with_metric(
    *,
    retention_curve: list[dict[str, float]],
    chapters: list[dict[str, object]],
    duration_s: float,
    add_execs: bool = True,
) -> str:
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.publishing.models import PublishJob

    channel = Channel.objects.create(
        name='Retention Ch',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='ret_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={},
        topic='test',
    )
    job = PublishJob.objects.create(run=run, channel=channel)
    from server.apps.analytics.models import PublishJobMetric

    PublishJobMetric.objects.create(
        publish_job=job,
        retention_curve=retention_curve,
    )
    if add_execs:
        StageExecution.objects.create(
            run=run,
            stage_key='outline',
            status=StageStatus.SUCCEEDED,
            output={'chapters': chapters},
        )
        StageExecution.objects.create(
            run=run,
            stage_key='assembly',
            status=StageStatus.SUCCEEDED,
            output={'duration_s': duration_s},
        )
    return str(channel.id)


@pytest.mark.django_db(transaction=True)
def test_compute_soft_spots_flags_underperforming_device() -> None:
    channel_id = _seed_run_with_metric(
        retention_curve=[
            {'elapsed_ratio': 0.1, 'relative_performance': 0.2},
            {'elapsed_ratio': 0.2, 'relative_performance': 0.3},
            {'elapsed_ratio': 0.3, 'relative_performance': 0.1},
        ],
        chapters=[{'device': 'open_loop', 'target_seconds': 100}],
        duration_s=100.0,
    )
    summary = _run(compute_soft_spots(channel_id))
    assert 'open_loop' in summary
    assert 'soft spots' in summary


@pytest.mark.django_db(transaction=True)
def test_compute_soft_spots_empty_when_device_performs_well() -> None:
    channel_id = _seed_run_with_metric(
        retention_curve=[
            {'elapsed_ratio': 0.1, 'relative_performance': 0.9},
            {'elapsed_ratio': 0.2, 'relative_performance': 0.8},
            {'elapsed_ratio': 0.3, 'relative_performance': 0.95},
        ],
        chapters=[{'device': 'payoff', 'target_seconds': 100}],
        duration_s=100.0,
    )
    assert _run(compute_soft_spots(channel_id)) == ''


@pytest.mark.django_db(transaction=True)
def test_compute_soft_spots_skips_metric_with_empty_curve() -> None:
    channel_id = _seed_run_with_metric(
        retention_curve=[],
        chapters=[{'device': 'open_loop', 'target_seconds': 100}],
        duration_s=100.0,
    )
    assert _run(compute_soft_spots(channel_id)) == ''


@pytest.mark.django_db(transaction=True)
def test_compute_soft_spots_ignores_devices_with_too_few_samples() -> None:
    channel_id = _seed_run_with_metric(
        retention_curve=[
            {'elapsed_ratio': 0.1, 'relative_performance': 0.1},
            {'elapsed_ratio': 0.2, 'relative_performance': 0.2},
        ],
        chapters=[{'device': 'open_loop', 'target_seconds': 100}],
        duration_s=100.0,
    )
    assert _run(compute_soft_spots(channel_id)) == ''


@pytest.mark.django_db(transaction=True)
def test_compute_soft_spots_skips_run_missing_stage_executions() -> None:
    channel_id = _seed_run_with_metric(
        retention_curve=[
            {'elapsed_ratio': 0.1, 'relative_performance': 0.2},
            {'elapsed_ratio': 0.2, 'relative_performance': 0.3},
            {'elapsed_ratio': 0.3, 'relative_performance': 0.1},
        ],
        chapters=[],
        duration_s=0.0,
        add_execs=False,
    )
    assert _run(compute_soft_spots(channel_id)) == ''
