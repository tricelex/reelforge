"""YouTube Data API v3 client for demand-grounded ideation.

Public search/statistics only. Uses a simple API key (YOUTUBE_DATA_API_KEY),
not per-channel OAuth, since it only reads public video/channel data.
"""

import re
from typing import Any
from urllib.parse import urlparse

import httpx

from server.apps.generation.clients._google_api_common import classify_response
from server.common.exceptions import FatalProviderError

_SEARCH_URL = 'https://www.googleapis.com/youtube/v3/search'
_VIDEOS_URL = 'https://www.googleapis.com/youtube/v3/videos'
_CHANNELS_URL = 'https://www.googleapis.com/youtube/v3/channels'
_MIN_DAYS_SINCE_PUBLISH = 0.5
_MIN_SUBSCRIBER_FLOOR = 1000
_CHANNEL_ID_RE = re.compile(r'^UC[\w-]{21,}$')
_YOUTUBE_HOSTS = frozenset({
    'youtube.com',
    'www.youtube.com',
    'm.youtube.com',
    'youtu.be',
    'www.youtu.be',
})
_MAX_SEARCH_ITEMS = 50


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


def _parse_bare_channel_ref(raw: str) -> tuple[str, str] | None:
    if raw.startswith('@') and '/' not in raw:
        return 'handle', raw.lstrip('@')
    if '://' not in raw and '/' not in raw and _CHANNEL_ID_RE.match(raw):
        return 'id', raw
    return None


def _parse_channel_path(parts: list[str]) -> tuple[str, str] | None:
    head = parts[0]
    if head == 'channel' and len(parts) >= 2:
        return 'id', parts[1]
    if head.startswith('@'):
        return 'handle', head.lstrip('@')
    if head == 'c' and len(parts) >= 2:
        return 'custom', parts[1]
    if head == 'user' and len(parts) >= 2:
        return 'username', parts[1]
    if len(parts) == 1 and head not in {'watch', 'results', 'feed'}:
        return 'custom', head
    return None


def parse_youtube_channel_ref(value: str) -> tuple[str, str]:
    """Parse a channel URL, @handle, or UC id into (kind, token).

    kind is one of ``id``, ``handle``, ``username``, ``custom``.
    """
    raw = value.strip()
    if not raw:
        msg = 'YouTube channel URL is required'
        raise ValueError(msg)
    bare = _parse_bare_channel_ref(raw)
    if bare is not None:
        return bare

    parsed = urlparse(raw if '://' in raw else f'https://{raw}')
    host = (parsed.hostname or '').lower()
    if host not in _YOUTUBE_HOSTS:
        msg = f'Not a YouTube URL: {value}'
        raise ValueError(msg)
    parts = [part for part in parsed.path.split('/') if part]
    parsed_path = _parse_channel_path(parts) if parts else None
    if parsed_path is not None:
        return parsed_path
    msg = f'Could not parse YouTube channel from: {value}'
    raise ValueError(msg)


async def _channels_list(
    api_key: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    query = {
        'part': 'snippet,statistics,brandingSettings',
        'key': api_key,
        **params,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(_CHANNELS_URL, params=query)
    _classify_response(resp)
    items = list(resp.json().get('items', []))
    if not items:
        msg = 'YouTube channel not found'
        raise FatalProviderError(msg, provider='youtube_search')
    return dict(items[0])


async def _search_channels(query: str, api_key: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _SEARCH_URL,
            params={
                'part': 'snippet',
                'q': query,
                'type': 'channel',
                'maxResults': 1,
                'key': api_key,
            },
        )
    _classify_response(resp)
    items = list(resp.json().get('items', []))
    if not items:
        msg = 'YouTube channel not found'
        raise FatalProviderError(msg, provider='youtube_search')
    channel_id = items[0].get('id', {}).get('channelId', '')
    if not channel_id:
        msg = 'YouTube channel not found'
        raise FatalProviderError(msg, provider='youtube_search')
    return str(channel_id)


async def resolve_channel(
    url_or_ref: str,
    api_key: str,
) -> dict[str, Any]:
    """Resolve a URL/handle to channels.list snippet+statistics+branding."""
    kind, token = parse_youtube_channel_ref(url_or_ref)
    if kind == 'id':
        return await _channels_list(api_key, {'id': token})
    if kind == 'handle':
        return await _channels_list(api_key, {'forHandle': token})
    if kind == 'username':
        return await _channels_list(api_key, {'forUsername': token})
    channel_id = await _search_channels(token, api_key)
    return await _channels_list(api_key, {'id': channel_id})


async def list_channel_videos(
    channel_id: str,
    api_key: str,
    *,
    order: str = 'date',
    max_results: int = 15,
) -> list[dict[str, Any]]:
    """search.list videos scoped to one channel (recent or popular)."""
    capped = min(max(max_results, 1), _MAX_SEARCH_ITEMS)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _SEARCH_URL,
            params={
                'part': 'snippet',
                'channelId': channel_id,
                'type': 'video',
                'order': order,
                'maxResults': capped,
                'key': api_key,
            },
        )
    _classify_response(resp)
    return list(resp.json().get('items', []))
