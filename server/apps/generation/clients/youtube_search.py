"""YouTube Data API v3 client for demand-grounded ideation.

Public search/statistics only. Uses a simple API key (YOUTUBE_DATA_API_KEY),
not per-channel OAuth, since it only reads public video/channel data.
"""

from typing import Any

import httpx

from server.apps.generation.clients._google_api_common import classify_response

_SEARCH_URL = 'https://www.googleapis.com/youtube/v3/search'
_VIDEOS_URL = 'https://www.googleapis.com/youtube/v3/videos'
_CHANNELS_URL = 'https://www.googleapis.com/youtube/v3/channels'
_MIN_DAYS_SINCE_PUBLISH = 0.5
_MIN_SUBSCRIBER_FLOOR = 1000


def _classify_response(resp: httpx.Response) -> None:
    classify_response(resp, provider='youtube_search')


def compute_outlier_score(
    view_count: int,
    subscriber_count: int,
    days_since_publish: float,
) -> float:
    """Views-per-subscriber, boosted by recency (faster views = higher)."""
    subs = max(subscriber_count, _MIN_SUBSCRIBER_FLOOR)
    days = max(days_since_publish, _MIN_DAYS_SINCE_PUBLISH)
    views_per_sub = view_count / subs
    recency_boost = 30.0 / days
    return views_per_sub * (1.0 + recency_boost)


async def search_videos(
    query: str,
    api_key: str,
    published_after: str | None = None,
    max_results: int = 25,
) -> list[dict[str, Any]]:
    """youtube#search.list — up to max_results videos ordered by view count."""
    params: dict[str, Any] = {
        'part': 'snippet',
        'q': query,
        'type': 'video',
        'maxResults': max_results,
        'order': 'viewCount',
        'key': api_key,
    }
    if published_after:
        params['publishedAfter'] = published_after
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(_SEARCH_URL, params=params)
    _classify_response(resp)
    return list(resp.json().get('items', []))


async def get_video_statistics(
    video_ids: list[str],
    api_key: str,
) -> list[dict[str, Any]]:
    """youtube#videos.list?part=statistics,snippet for a batch of video IDs."""
    if not video_ids:
        return []
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _VIDEOS_URL,
            params={
                'part': 'statistics,snippet',
                'id': ','.join(video_ids),
                'key': api_key,
            },
        )
    _classify_response(resp)
    return list(resp.json().get('items', []))


async def get_channel_statistics(
    channel_ids: list[str],
    api_key: str,
) -> list[dict[str, Any]]:
    """youtube#channels.list?part=statistics for a batch of channel IDs."""
    if not channel_ids:
        return []
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _CHANNELS_URL,
            params={
                'part': 'statistics',
                'id': ','.join(channel_ids),
                'key': api_key,
            },
        )
    _classify_response(resp)
    return list(resp.json().get('items', []))
