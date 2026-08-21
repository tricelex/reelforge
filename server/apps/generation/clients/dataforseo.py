"""DataForSEO YouTube Live SERP client.

HTTP Basic auth (DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD). Live Advanced
endpoints wait in-process so a TaskIQ job can block on them. Payloads are
truncated to keep pydantic-ai tool results inside context budgets.
"""

from typing import Any

import httpx

from server.common.exceptions import FatalProviderError, RetryableProviderError

_BASE = 'https://api.dataforseo.com'
_RETRYABLE_CODES = frozenset({429, 500, 502, 503, 504})
_OK_TASK_CODES = frozenset({20000, 20100})
_LIVE_TIMEOUT_S = 90.0
_MAX_ITEMS = 12
_MAX_CHARACTERS_PER_FIELD = 1_200
_TEXT_KEYS = frozenset({
    'description',
    'title',
    'text',
    'comment',
    'subtitle',
    'subtitles',
    'transcript',
})


def _truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ''
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return f'{text[: max_chars - 3]}...'


def _truncate_value(value: Any, max_chars: int) -> Any:
    if isinstance(value, str):
        return _truncate_text(value, max_chars)
    if isinstance(value, dict):
        return _truncate_item(value, max_chars)
    if isinstance(value, list):
        capped = value[:_MAX_ITEMS]
        return [_truncate_value(item, max_chars) for item in capped]
    return value


def _truncate_item(item: dict[str, Any], max_chars: int) -> dict[str, Any]:
    truncated: dict[str, Any] = {}
    for key, value in item.items():
        if key in _TEXT_KEYS and isinstance(value, str):
            truncated[key] = _truncate_text(value, max_chars)
        else:
            truncated[key] = _truncate_value(value, max_chars)
    return truncated


def _classify_http(resp: httpx.Response) -> None:
    if resp.status_code in _RETRYABLE_CODES:
        raise RetryableProviderError(
            f'DataForSEO {resp.status_code}: {resp.text[:200]}',
            provider='dataforseo',
            status_code=resp.status_code,
        )
    if not resp.is_success:
        raise FatalProviderError(
            f'DataForSEO {resp.status_code}: {resp.text[:200]}',
            provider='dataforseo',
        )


def _extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = payload.get('tasks') or []
    if not tasks:
        return []
    task = tasks[0]
    status = int(task.get('status_code') or 0)
    if status not in _OK_TASK_CODES:
        message = str(task.get('status_message') or f'status {status}')
        raise FatalProviderError(message, provider='dataforseo')
    results = task.get('result') or []
    if not results:
        return []
    first = results[0] or {}
    raw_items = first.get('items') or first.get('subtitles') or []
    if not isinstance(raw_items, list):
        return []
    return [
        _truncate_item(item, _MAX_CHARACTERS_PER_FIELD)
        for item in raw_items[:_MAX_ITEMS]
        if isinstance(item, dict)
    ]


async def _live_post(
    path: str,
    body: list[dict[str, Any]],
    login: str,
    password: str,
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_LIVE_TIMEOUT_S) as client:
        resp = await client.post(
            f'{_BASE}{path}',
            auth=(login, password),
            json=body,
        )
    _classify_http(resp)
    return _extract_items(resp.json())


def _location_task(**fields: Any) -> dict[str, Any]:
    task: dict[str, Any] = {
        'location_code': 2840,
        'language_code': 'en',
        'device': 'desktop',
    }
    task.update(fields)
    return task


async def youtube_organic_search(
    keyword: str,
    login: str,
    password: str,
    *,
    block_depth: int = 20,
) -> list[dict[str, Any]]:
    """POST /v3/serp/youtube/organic/live/advanced."""
    return await _live_post(
        '/v3/serp/youtube/organic/live/advanced',
        [_location_task(keyword=keyword, block_depth=block_depth)],
        login,
        password,
    )


async def youtube_video_info(
    video_id: str,
    login: str,
    password: str,
) -> list[dict[str, Any]]:
    """POST /v3/serp/youtube/video_info/live/advanced."""
    return await _live_post(
        '/v3/serp/youtube/video_info/live/advanced',
        [_location_task(video_id=video_id)],
        login,
        password,
    )


async def youtube_video_comments(
    video_id: str,
    login: str,
    password: str,
    *,
    depth: int = 20,
) -> list[dict[str, Any]]:
    """POST /v3/serp/youtube/video_comments/live/advanced."""
    return await _live_post(
        '/v3/serp/youtube/video_comments/live/advanced',
        [_location_task(video_id=video_id, depth=depth)],
        login,
        password,
    )


async def youtube_video_subtitles(
    video_id: str,
    login: str,
    password: str,
) -> list[dict[str, Any]]:
    """POST /v3/serp/youtube/video_subtitles/live/advanced."""
    return await _live_post(
        '/v3/serp/youtube/video_subtitles/live/advanced',
        [_location_task(video_id=video_id)],
        login,
        password,
    )
