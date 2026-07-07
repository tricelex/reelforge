"""TaskIQ broker tasks for pipeline execution."""

import uuid
from typing import TYPE_CHECKING, Any, cast

from asgiref.sync import sync_to_async

from server.apps.generation.clients import youtube as yt_client
from server.common.broker import broker

if TYPE_CHECKING:
    from server.apps.publishing.models import PublishJob

_SWAP_MIN_AGE_H = 24
_SWAP_MAX_AGE_H = 48


@broker.task(retry_on_error=False, queue='api')
async def execute_stage(execution_id: str) -> None:
    """Execute one pipeline stage; manages its own retry logic."""
    from server.apps.pipelines.services.executor import (  # noqa: PLC0415
        execute_stage_impl,
    )

    await execute_stage_impl(execution_id)


@broker.task(retry_on_error=False, queue='orchestrator')
async def advance_pipeline(run_id: str) -> None:
    """Re-evaluate the DAG and enqueue any newly-ready stages."""
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        advance_pipeline_impl,
    )

    await advance_pipeline_impl(run_id)


@broker.task(retry_on_error=False, queue='api')
async def resume_publish_held_runs() -> None:
    """Resume every PUBLISH_HOLD run — called once daily by a scheduler.

    Uses ``resume_run_impl`` (not ``advance_pipeline_impl``) so the run
    transitions out of PUBLISH_HOLD back to RUNNING before the DAG is
    re-evaluated; a run still over its daily cap re-parks at PUBLISH_HOLD.
    """
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineRun,
        RunStatus,
    )
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        resume_run_impl,
    )

    run_ids = [
        str(run_id)
        async for run_id in PipelineRun.objects.filter(
            status=RunStatus.PUBLISH_HOLD,
        ).values_list('id', flat=True)
    ]
    for run_id in run_ids:
        await resume_run_impl(run_id)


async def _download_thumbnail_bytes(asset_id: str) -> bytes:  # pragma: no cover
    from server.apps.assets.models import Asset  # noqa: PLC0415

    asset = await Asset.objects.aget(id=asset_id)
    return asset.file.read()  # type: ignore[no-any-return]


def _channel_median_ctr(
    channel_id: uuid.UUID,
    exclude_job_id: uuid.UUID,
) -> float | None:
    from server.apps.analytics.models import PublishJobMetric  # noqa: PLC0415

    # One value per job (its latest snapshot) so a job tracked over many
    # days is not counted repeatedly when computing the channel median.
    raw = (
        PublishJobMetric.objects
        .filter(
            publish_job__channel_id=channel_id,
            impressions_ctr__isnull=False,
        )
        .exclude(publish_job_id=exclude_job_id)
        .order_by('publish_job_id', '-pulled_at')
        .distinct('publish_job_id')
        .values_list('impressions_ctr', flat=True)
    )
    values = sorted(cast('list[float]', list(raw)))
    if not values:
        return None
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


async def _next_untested_candidate(
    job: 'PublishJob',
) -> dict[str, Any] | None:
    """Return the highest-ranked candidate this job hasn't tested yet.

    Marks the job as tested and returns None when the pool is exhausted.
    """
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    thumb_exec = await StageExecution.objects.filter(
        run_id=job.run_id,
        stage_key='thumbnail',
        status=StageStatus.SUCCEEDED,
    ).afirst()
    if thumb_exec is None:
        return None
    candidates: list[dict[str, Any]] = thumb_exec.output.get('candidates', [])
    tested = set(job.tested_candidate_ranks)
    current_rank = next(
        (
            c['rank']
            for c in candidates
            if c['asset_id'] == job.thumbnail_asset_id
        ),
        None,
    )
    if current_rank is not None:
        tested.add(current_rank)
    untested = [c for c in candidates if c['rank'] not in tested]
    if not untested:
        job.thumbnail_tested = True
        await job.asave(update_fields=['thumbnail_tested'])
        return None
    return untested[0]


async def _apply_thumbnail_swap(
    job: 'PublishJob',
    next_candidate: dict[str, Any],
) -> None:
    """Set the next thumbnail candidate on YouTube and persist the state."""
    from server.apps.channels.models import YouTubeCredential  # noqa: PLC0415

    try:
        credential = await YouTubeCredential.objects.aget(channel=job.channel)
    except YouTubeCredential.DoesNotExist:
        return
    access_token = await yt_client.refresh_token_if_needed(credential)
    thumb_bytes = await _download_thumbnail_bytes(next_candidate['asset_id'])
    await yt_client.set_thumbnail(
        access_token,
        job.youtube_video_id,
        thumb_bytes,
    )

    job.thumbnail_asset_id = next_candidate['asset_id']
    job.thumbnail_tested = True
    job.tested_candidate_ranks = [
        *job.tested_candidate_ranks,
        next_candidate['rank'],
    ]
    await job.asave(
        update_fields=[
            'thumbnail_asset_id',
            'thumbnail_tested',
            'tested_candidate_ranks',
        ],
    )


async def _maybe_swap_job(job: 'PublishJob') -> None:
    """Swap one job's thumbnail if its CTR is below the channel median."""
    from server.apps.analytics.models import PublishJobMetric  # noqa: PLC0415

    metric = await (
        PublishJobMetric.objects
        .filter(
            publish_job=job,
            impressions_ctr__isnull=False,
        )
        .order_by('-pulled_at')
        .afirst()
    )
    if metric is None:
        return
    median = await sync_to_async(_channel_median_ctr)(job.channel_id, job.id)
    ctr = cast('float', metric.impressions_ctr)
    if median is None or ctr >= median:
        return
    next_candidate = await _next_untested_candidate(job)
    if next_candidate is None:
        return
    await _apply_thumbnail_swap(job, next_candidate)


@broker.task(retry_on_error=False, queue='api')
async def swap_underperforming_thumbnails() -> None:
    """Swap to an unused thumbnail candidate for underperforming jobs.

    Targets jobs 24-48h old with below-median CTR — at most once per job
    (tracked via thumbnail_tested).
    """
    import datetime  # noqa: PLC0415

    import django.utils.timezone as tz  # noqa: PLC0415

    from server.apps.publishing.models import (  # noqa: PLC0415
        PublishJob,
        PublishStatus,
    )

    now = tz.now()
    window_start = now - datetime.timedelta(hours=_SWAP_MAX_AGE_H)
    window_end = now - datetime.timedelta(hours=_SWAP_MIN_AGE_H)

    jobs = [
        job
        async for job in PublishJob.objects.filter(
            status=PublishStatus.COMPLETED,
            thumbnail_tested=False,
            created_at__gte=window_start,
            created_at__lte=window_end,
        ).select_related('channel', 'run')
    ]
    for job in jobs:
        await _maybe_swap_job(job)
