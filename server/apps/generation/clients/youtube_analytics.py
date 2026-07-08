"""YouTube Analytics API client — per-video performance + retention curve.

Free API, quota-limited like the Data API. Requires the
yt-analytics.readonly OAuth scope on the connected channel's credential.
"""

from typing import Any

import httpx

from server.apps.generation.clients._google_api_common import classify_response
from server.common.exceptions import FatalProviderError, RetryableProviderError

_REPORTS_URL = 'https://youtubeanalytics.googleapis.com/v2/reports'


def _classify_response(resp: httpx.Response) -> None:
    classify_response(resp, provider='youtube_analytics')


async def _query_report(
    access_token: str,
    channel_youtube_id: str,
    video_id: str,
    metrics: str,
    dimensions: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        'ids': f'channel=={channel_youtube_id}',
        'startDate': '2020-01-01',
        'endDate': '2030-01-01',
        'metrics': metrics,
        'filters': f'video=={video_id}',
    }
    if dimensions:
        params['dimensions'] = dimensions
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _REPORTS_URL,
            params=params,
            headers={'Authorization': f'Bearer {access_token}'},
        )
    _classify_response(resp)
    return dict(resp.json())


async def _fetch_impressions(
    access_token: str,
    channel_youtube_id: str,
    video_id: str,
) -> tuple[int | None, float | None]:
    """Best-effort impressions + CTR; None when the API has no data yet.

    Impressions/CTR belong to a separate Analytics metric set with its own
    reporting availability, so a provider error or empty result is treated
    as "not enough data yet" rather than failing the whole report.
    """
    try:
        report = await _query_report(
            access_token,
            channel_youtube_id,
            video_id,
            metrics='impressions,impressionsClickThroughRate',
        )
    except (FatalProviderError, RetryableProviderError):
        return None, None
    rows = report.get('rows', [])
    if not rows:
        return None, None
    impressions, ctr = rows[0]
    return int(impressions), float(ctr)


async def fetch_video_report(
    access_token: str,
    channel_youtube_id: str,
    video_id: str,
) -> dict[str, Any]:
    """Fetch summary metrics + the 100-point audience-retention curve."""
    summary = await _query_report(
        access_token,
        channel_youtube_id,
        video_id,
        metrics='views,averageViewDuration,averageViewPercentage',
    )
    summary_rows = summary.get('rows', [])
    views, avg_duration, avg_pct = (
        summary_rows[0] if summary_rows else (0, 0.0, 0.0)
    )

    retention = await _query_report(
        access_token,
        channel_youtube_id,
        video_id,
        metrics='audienceWatchRatio,relativeRetentionPerformance',
        dimensions='elapsedVideoTimeRatio',
    )
    retention_curve = [
        {
            'elapsed_ratio': row[0],
            'watch_ratio': row[1],
            'relative_performance': row[2],
        }
        for row in retention.get('rows', [])
    ]

    impressions, impressions_ctr = await _fetch_impressions(
        access_token,
        channel_youtube_id,
        video_id,
    )

    return {
        'views': int(views),
        'avg_view_duration_s': float(avg_duration),
        'avg_view_percentage': float(avg_pct),
        'retention_curve': retention_curve,
        'impressions': impressions,
        'impressions_ctr': impressions_ctr,
    }
