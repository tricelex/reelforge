"""TaskIQ tasks for analytics view maintenance."""

from typing import Any

import structlog

from server.apps.generation.clients import youtube as yt_client
from server.apps.generation.clients.youtube_analytics import fetch_video_report
from server.common.broker import broker

logger = structlog.get_logger(__name__)


@broker.task(retry_on_error=False, queue='api')
async def refresh_analytics_views() -> None:
    """REFRESH MATERIALIZED VIEW CONCURRENTLY for all three analytics views."""
    from asgiref.sync import sync_to_async  # noqa: PLC0415
    from django.db import connection  # noqa: PLC0415

    views = [
        'analytics_run_cost_summary',
        'analytics_channel_roi',
        'analytics_stage_performance',
    ]

    def _refresh() -> None:
        with connection.cursor() as cursor:
            for view in views:
                cursor.execute(
                    f'REFRESH MATERIALIZED VIEW CONCURRENTLY {view}',
                )

    await sync_to_async(_refresh)()


async def _get_channel_youtube_id(access_token: str) -> str:  # pragma: no cover
    """Look up the connected channel's own YouTube channel ID.

    Implemented as a thin wrapper so tests can patch it directly; the real
    body calls channels.list?mine=true with the bearer token and returns
    items[0]['id'].
    """
    import httpx  # noqa: PLC0415

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            'https://www.googleapis.com/youtube/v3/channels',
            params={'part': 'id', 'mine': 'true'},
            headers={'Authorization': f'Bearer {access_token}'},
        )
    resp.raise_for_status()
    return str(resp.json()['items'][0]['id'])


async def _resolve_channel_access(
    job: Any,
    access_tokens: dict[Any, str],
    channel_youtube_ids: dict[Any, str],
) -> tuple[str, str] | None:
    """Return (access_token, channel_youtube_id) for job's channel, cached
    per channel_id so a batch of jobs on the same channel only refreshes the
    token / resolves the YouTube channel ID once. Returns None (and logs) if
    the channel has no usable credential.
    """
    from server.apps.channels.models import YouTubeCredential  # noqa: PLC0415

    access_token = access_tokens.get(job.channel_id)
    if access_token is None:
        try:
            credential = await YouTubeCredential.objects.aget(
                channel=job.channel,
            )
        except YouTubeCredential.DoesNotExist:
            logger.warning(
                'publish_job_metric_no_credential',
                channel_id=str(job.channel_id),
            )
            return None
        access_token = await yt_client.refresh_token_if_needed(credential)
        access_tokens[job.channel_id] = access_token

    channel_youtube_id = channel_youtube_ids.get(job.channel_id)
    if channel_youtube_id is None:
        channel_youtube_id = await _get_channel_youtube_id(access_token)
        channel_youtube_ids[job.channel_id] = channel_youtube_id
    return access_token, channel_youtube_id


async def _pull_one_job_metric(
    job: Any,
    access_tokens: dict[Any, str],
    channel_youtube_ids: dict[Any, str],
) -> None:
    """Fetch and persist one PublishJobMetric row for `job`.

    Isolated per job so one channel's failure (stale credential missing the
    yt-analytics.readonly scope, a transient API error, etc.) doesn't abort
    metric collection for every other channel in the same batch.
    """
    from server.apps.analytics.models import PublishJobMetric  # noqa: PLC0415

    resolved = await _resolve_channel_access(
        job,
        access_tokens,
        channel_youtube_ids,
    )
    if resolved is None:
        return
    access_token, channel_youtube_id = resolved

    report = await fetch_video_report(
        access_token,
        channel_youtube_id,
        job.youtube_video_id,
    )
    await PublishJobMetric.objects.acreate(
        publish_job=job,
        views=report['views'],
        avg_view_duration_s=report['avg_view_duration_s'],
        avg_view_percentage=report['avg_view_percentage'],
        retention_curve=report['retention_curve'],
        impressions=report['impressions'],
        impressions_ctr=report['impressions_ctr'],
    )


@broker.task(retry_on_error=False, queue='api')
async def pull_publish_job_metrics() -> None:
    """Pull YouTube Analytics for PublishJobs completed in the last 30 days."""
    import datetime  # noqa: PLC0415

    import django.utils.timezone as tz  # noqa: PLC0415

    from server.apps.publishing.models import (  # noqa: PLC0415
        PublishJob,
        PublishStatus,
    )

    cutoff = tz.now() - datetime.timedelta(days=30)
    jobs = [
        job
        async for job in PublishJob.objects.filter(
            status=PublishStatus.COMPLETED,
            created_at__gte=cutoff,
        ).select_related('channel')
    ]
    # Cached per channel_id (quota discipline + avoid redundant token refresh).
    access_tokens: dict[Any, str] = {}
    channel_youtube_ids: dict[Any, str] = {}
    for job in jobs:
        try:
            await _pull_one_job_metric(job, access_tokens, channel_youtube_ids)
        except Exception:
            logger.warning(
                'publish_job_metric_pull_failed',
                job_id=str(job.id),
                channel_id=str(job.channel_id),
                exc_info=True,
            )
            continue
