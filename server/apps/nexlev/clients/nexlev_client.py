"""Async NexLev API client — normalizes NexLev's inconsistent envelopes.

Every function returns plain dict/list JSON (not yet a msgspec struct);
NexLevService (Tasks 3-5) does the struct conversion after merging with
persisted records.
"""

from typing import Any

import httpx

from server.common.exceptions import FatalProviderError, RetryableProviderError

_PROVIDER = 'nexlev'
_TIMEOUT = 30.0


def _auth_headers(api_key: str) -> dict[str, str]:
    return {'Authorization': f'Bearer {api_key}'}


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code == httpx.codes.UNAUTHORIZED:
        msg = 'NexLev request unauthorized'
        raise FatalProviderError(msg, provider=_PROVIDER, error_code='401')
    if response.status_code == httpx.codes.NOT_FOUND:
        msg = 'NexLev resource not found'
        raise FatalProviderError(msg, provider=_PROVIDER, error_code='404')
    if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
        msg = 'NexLev quota or rate limit exceeded'
        raise RetryableProviderError(
            msg,
            provider=_PROVIDER,
            status_code=response.status_code,
        )
    if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
        msg = f'NexLev upstream error {response.status_code}'
        raise RetryableProviderError(
            msg,
            provider=_PROVIDER,
            status_code=response.status_code,
        )
    if not response.is_success:
        msg = f'NexLev unexpected status {response.status_code}'
        raise FatalProviderError(
            msg,
            provider=_PROVIDER,
            error_code=str(response.status_code),
        )


def _parse_json(response: httpx.Response) -> Any:
    _raise_for_status(response)
    return response.json()


async def get_channel_about(
    channel_id: str,
    *,
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    """GET /api/external/channels/about?id=<channel_id>. 1 quota."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f'{base_url}/api/external/channels/about',
            params={'id': channel_id},
            headers=_auth_headers(api_key),
        )
    result: dict[str, Any] = _parse_json(response)
    return result


async def get_channel_outliers(
    channel_id: str,
    *,
    api_key: str,
    base_url: str,
    max_videos: int = 30,
    min_outlier_threshold: float = 2.0,
) -> list[dict[str, Any]]:
    """GET /api/external/channels/outliers. 1 quota."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f'{base_url}/api/external/channels/outliers',
            params={
                'id': channel_id,
                'maxVideos': max_videos,
                'minOutlierThreshold': min_outlier_threshold,
            },
            headers=_auth_headers(api_key),
        )
    data = _parse_json(response)
    outliers = data.get('outliers', [])
    return list(outliers) if isinstance(outliers, list) else []


async def get_channel_analytics(
    channel_id: str,
    *,
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    """POST /api/external/analytics/channel-analytics. 10 quota.

    Flattens the nested `about` block and top-level categories/tags into
    one dict matching NexLevChannelAnalytics.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            f'{base_url}/api/external/analytics/channel-analytics',
            json={'channelId': channel_id},
            headers=_auth_headers(api_key),
        )
    data = _parse_json(response)
    first = data[0] if isinstance(data, list) and data else {}
    about = first.get('about', {})
    return {
        'subscriberCount': about.get('subscriberCount', 0),
        'viewCount': about.get('viewCount', 0),
        'videoCount': about.get('videoCount', 0),
        'country': about.get('country', ''),
        'categories': first.get('categories', []),
        'tags': first.get('tags', []),
    }


async def get_similar_channels(
    channel_id: str,
    *,
    api_key: str,
    base_url: str,
) -> list[dict[str, Any]]:
    """POST /api/external/similar-channels/search. 20 quota.

    Flattens each item's `about` block into a flat channelId/channelName
    dict matching NexLevSimilarChannel.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            f'{base_url}/api/external/similar-channels/search',
            json={'channelId': channel_id, 'channelType': 'all', 'level': 1},
            headers=_auth_headers(api_key),
        )
    data = _parse_json(response)
    items = data.get('data', []) if isinstance(data, dict) else []
    return [
        {
            'channelId': item.get('about', {}).get('channelId', ''),
            'channelName': item.get('about', {}).get('channelName', ''),
            'similarityScore': item.get('similarityScore', 0),
        }
        for item in items
    ]


async def get_niche_overview(
    channel_id: str,
    *,
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    """POST /api/external/niche-overview/analyze. 20 quota."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            f'{base_url}/api/external/niche-overview/analyze',
            json={'channelId': channel_id},
            headers=_auth_headers(api_key),
        )
    result: dict[str, Any] = _parse_json(response)
    return result


async def get_video_details(
    video_id: str,
    *,
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    """GET /api/external/videos/details. 1 quota. Unwraps list envelope.

    Raises FatalProviderError if NexLev has no data for this video_id
    (it responds 200 with an empty list rather than 404).
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f'{base_url}/api/external/videos/details',
            params={'videoId': video_id},
            headers=_auth_headers(api_key),
        )
    data = _parse_json(response)
    if not isinstance(data, list) or not data:
        msg = f'NexLev has no data for video {video_id}'
        raise FatalProviderError(msg, provider=_PROVIDER, error_code='404')
    return dict(data[0])


async def get_video_transcript(
    video_id: str,
    *,
    api_key: str,
    base_url: str,
) -> list[dict[str, Any]]:
    """GET /api/external/videos/transcript. 1 quota."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f'{base_url}/api/external/videos/transcript',
            params={'videoId': video_id},
            headers=_auth_headers(api_key),
        )
    data = _parse_json(response)
    first = data[0] if isinstance(data, list) and data else {}
    transcript = first.get('transcript', [])
    return list(transcript) if isinstance(transcript, list) else []


async def get_video_comments(
    video_id: str,
    *,
    api_key: str,
    base_url: str,
) -> list[dict[str, Any]]:
    """GET /api/external/videos/comments. 1 quota."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f'{base_url}/api/external/videos/comments',
            params={'videoId': video_id},
            headers=_auth_headers(api_key),
        )
    data = _parse_json(response)
    comments = data.get('data', [])
    return list(comments) if isinstance(comments, list) else []


async def search_youtube(
    query: str,
    *,
    api_key: str,
    base_url: str,
    search_type: str | None = None,
) -> list[dict[str, Any]]:
    """GET /api/external/youtube/search. 1 quota, 20 req/min limit."""
    params: dict[str, Any] = {'query': query}
    if search_type is not None:
        params['type'] = search_type
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f'{base_url}/api/external/youtube/search',
            params=params,
            headers=_auth_headers(api_key),
        )
    data = _parse_json(response)
    results = data.get('results', [])
    return list(results) if isinstance(results, list) else []


async def create_channel_analysis_job(
    channel_id: str,
    *,
    api_key: str,
    base_url: str,
) -> str:
    """GET .../channels/analysis/job/create. 20 quota. List envelope."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f'{base_url}/api/external/channels/analysis/job/create',
            params={'channel_id': channel_id},
            headers=_auth_headers(api_key),
        )
    data = _parse_json(response)
    first = data[0] if isinstance(data, list) and data else data
    return str(first['job_id'])


async def get_channel_analysis_result(
    job_id: str,
    *,
    api_key: str,
    base_url: str,
) -> dict[str, Any] | None:
    """GET .../channels/analysis/job/status. 1 quota.

    Returns None while `status != 'completed'` so the caller can poll.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f'{base_url}/api/external/channels/analysis/job/status',
            params={'job_id': job_id},
            headers=_auth_headers(api_key),
        )
    data: dict[str, Any] = _parse_json(response)
    if data.get('status') != 'completed':
        return None
    return data
