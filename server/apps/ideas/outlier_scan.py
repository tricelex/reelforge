"""Cached, quota-aware niche outlier scan.

Runs at most once/day per niche (per the Costs note in the design doc —
search.list is capped at ~100 calls/day/project).
"""

import datetime as dt
import uuid
from typing import TYPE_CHECKING

import django.utils.timezone as tz
from django.conf import settings

from server.apps.generation.clients.youtube_search import (
    compute_outlier_score,
    get_channel_statistics,
    get_video_statistics,
    search_videos,
)
from server.apps.ideas.logic.schemas import OutlierVideo

if TYPE_CHECKING:
    from server.apps.channels.models import NicheConfig

_CACHE_WINDOW = dt.timedelta(hours=24)
_MAX_RESULTS = 15


def _query_for_niche(niche: 'NicheConfig') -> str:
    """Build a search query from the niche's audience/angle."""
    parts = [niche.angle, niche.audience]
    return ' '.join(p for p in parts if p).strip() or 'documentary'


def _parse_days_since(published_at: str) -> float:
    published = dt.datetime.fromisoformat(published_at)
    return max((tz.now() - published).total_seconds() / 86400, 0.0)


async def run_niche_outlier_scan(niche: 'NicheConfig') -> list[OutlierVideo]:
    """Run a fresh scan against the YouTube Data API and persist the result."""
    from server.apps.ideas.models import NicheOutlierScan  # noqa: PLC0415

    api_key: str = getattr(settings, 'YOUTUBE_DATA_API_KEY', '')
    query = _query_for_niche(niche)

    search_items = await search_videos(
        query,
        api_key=api_key,
        max_results=_MAX_RESULTS,
    )
    video_ids = [
        item['id']['videoId']
        for item in search_items
        if item.get('id', {}).get('videoId')
    ]
    video_stats = await get_video_statistics(video_ids, api_key=api_key)

    channel_ids = list({
        item['snippet']['channelId']
        for item in video_stats
        if item.get('snippet', {}).get('channelId')
    })
    channel_stats = await get_channel_statistics(channel_ids, api_key=api_key)
    subs_by_channel = {
        c['id']: int(c.get('statistics', {}).get('subscriberCount', 0))
        for c in channel_stats
    }

    results: list[OutlierVideo] = []
    for item in video_stats:
        snippet = item.get('snippet', {})
        stats = item.get('statistics', {})
        view_count = int(stats.get('viewCount', 0))
        channel_id = snippet.get('channelId', '')
        subscriber_count = subs_by_channel.get(channel_id, 0)
        published_at = snippet.get('publishedAt', tz.now().isoformat())
        score = compute_outlier_score(
            view_count=view_count,
            subscriber_count=subscriber_count,
            days_since_publish=_parse_days_since(published_at),
        )
        results.append(
            OutlierVideo(
                video_id=item.get('id', ''),
                title=snippet.get('title', ''),
                channel_title=snippet.get('channelTitle', ''),
                view_count=view_count,
                published_at=published_at,
                outlier_score=score,
            ),
        )
    results.sort(key=lambda v: v.outlier_score, reverse=True)

    await NicheOutlierScan.objects.acreate(
        niche=niche,
        query=query,
        results=[r.model_dump() for r in results],
    )
    return results


def get_cached_scan(niche_id: str) -> list[OutlierVideo] | None:
    """Return the latest scan's results if it's less than 24h old, else None."""
    from server.apps.ideas.models import NicheOutlierScan  # noqa: PLC0415

    latest = (
        NicheOutlierScan.objects
        .filter(niche_id=uuid.UUID(niche_id))
        .order_by('-created_at')
        .first()
    )
    if latest is None or tz.now() - latest.created_at > _CACHE_WINDOW:
        return None
    return [OutlierVideo.model_validate(r) for r in latest.results]
