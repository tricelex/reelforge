"""Aggregate retention-curve data by chapter device.

Surfaces a channel's "known soft spots" back into future outline prompts.
"""

from typing import Any

_SOFT_SPOT_THRESHOLD = 0.5
_MIN_SAMPLES = 3
_RECENT_METRICS_LIMIT = 30


def _bucket_curve_by_device(
    retention_curve: list[dict[str, float]],
    chapter_boundaries: list[dict[str, Any]],
    total_duration_s: float,
) -> dict[str, list[float]]:
    """Map each curve point's relative_performance to its chapter's device."""
    buckets: dict[str, list[float]] = {}
    if total_duration_s <= 0:
        return buckets
    for point in retention_curve:
        elapsed_s = point['elapsed_ratio'] * total_duration_s
        for chapter in chapter_boundaries:
            if chapter['start_s'] <= elapsed_s < chapter['end_s']:
                buckets.setdefault(chapter['device'], []).append(
                    point['relative_performance'],
                )
                break
    return buckets


def _chapter_boundaries_from_outline(
    chapters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build cumulative [start_s, end_s) spans from chapters' target_seconds."""
    boundaries: list[dict[str, Any]] = []
    cursor = 0.0
    for ch in chapters:
        duration = float(ch.get('target_seconds', 0))
        boundaries.append(
            {
                'device': ch.get('device', ''),
                'start_s': cursor,
                'end_s': cursor + duration,
            },
        )
        cursor += duration
    return boundaries


async def _fetch_recent_metrics(channel_id: str) -> list[Any]:
    """Latest metrics with a non-empty retention curve, most recent first."""
    from server.apps.analytics.models import PublishJobMetric  # noqa: PLC0415

    return [
        metric
        async for metric in (
            PublishJobMetric.objects
            .filter(publish_job__channel_id=channel_id)
            .select_related('publish_job__run')
            .order_by('-pulled_at')[:_RECENT_METRICS_LIMIT]
        )
        if metric.retention_curve
    ]


async def _fetch_stage_executions_by_run(
    run_ids: set[Any],
) -> tuple[dict[Any, Any], dict[Any, Any]]:
    """One batched query for outline+assembly executions across all run_ids."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    outline_by_run: dict[Any, Any] = {}
    assembly_by_run: dict[Any, Any] = {}
    async for execution in StageExecution.objects.filter(
        run_id__in=run_ids,
        stage_key__in=('outline', 'assembly'),
        status=StageStatus.SUCCEEDED,
    ):
        by_run = (
            outline_by_run
            if execution.stage_key == 'outline'
            else assembly_by_run
        )
        by_run.setdefault(execution.run_id, execution)
    return outline_by_run, assembly_by_run


def _aggregate_buckets(
    metrics: list[Any],
    outline_by_run: dict[Any, Any],
    assembly_by_run: dict[Any, Any],
) -> dict[str, list[float]]:
    """Merge per-metric device buckets across every metric in `metrics`."""
    all_buckets: dict[str, list[float]] = {}
    for metric in metrics:
        run_id = metric.publish_job.run_id
        outline_exec = outline_by_run.get(run_id)
        assembly_exec = assembly_by_run.get(run_id)
        if outline_exec is None or assembly_exec is None:
            continue
        chapters = outline_exec.output.get('chapters', [])
        total_duration_s = float(assembly_exec.output.get('duration_s', 0))
        boundaries = _chapter_boundaries_from_outline(chapters)
        buckets = _bucket_curve_by_device(
            metric.retention_curve,
            boundaries,
            total_duration_s,
        )
        for device, values in buckets.items():
            all_buckets.setdefault(device, []).extend(values)
    return all_buckets


async def compute_soft_spots(channel_id: str) -> str:
    """Summarize which retention devices underperform for this channel.

    Returns '' when there isn't enough data (fewer than _MIN_SAMPLES points
    for every device) to say anything meaningful yet.

    Uses async ORM iteration throughout (this is called from an async
    pipeline stage) and batches the outline/assembly StageExecution lookups
    into a single query instead of two per metric.
    """
    metrics = await _fetch_recent_metrics(channel_id)
    if not metrics:
        return ''

    run_ids = {metric.publish_job.run_id for metric in metrics}
    outline_by_run, assembly_by_run = await _fetch_stage_executions_by_run(
        run_ids,
    )
    all_buckets = _aggregate_buckets(metrics, outline_by_run, assembly_by_run)

    soft_spots = [
        (device, sum(values) / len(values))
        for device, values in all_buckets.items()
        if len(values) >= _MIN_SAMPLES
        and (sum(values) / len(values)) < _SOFT_SPOT_THRESHOLD
    ]
    if not soft_spots:
        return ''

    lines = [
        f'chapters using the "{device}" retention device underperform '
        f'similar-length videos platform-wide (avg relative performance '
        f'{avg:.2f})'
        for device, avg in soft_spots
    ]
    return 'Known pacing soft spots on this channel: ' + '; '.join(lines) + '.'
