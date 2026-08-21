"""Tests for the DataForSEO YouTube Live client."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from server.apps.generation.clients.dataforseo import (
    youtube_organic_search,
    youtube_video_comments,
    youtube_video_info,
    youtube_video_subtitles,
)
from server.common.exceptions import FatalProviderError, RetryableProviderError


def _ok_payload(
    items: list[dict[str, object]],
) -> dict[str, object]:
    return {
        'status_code': 20000,
        'tasks': [
            {
                'status_code': 20000,
                'result': [{'items': items}],
            },
        ],
    }


def test_youtube_organic_search_returns_truncated_items() -> None:
    long_desc = 'x' * 5000
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = _ok_payload(
        [
            {
                'type': 'youtube_video',
                'title': 'Rome',
                'video_id': 'abc',
                'description': long_desc,
            },
        ],
    )

    async def _inner() -> list[dict[str, object]]:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            return await youtube_organic_search(
                'roman empire',
                login='user',
                password='pass',
            )

    items = asyncio.run(_inner())
    assert items[0]['video_id'] == 'abc'
    assert len(str(items[0]['description'])) < len(long_desc)


def test_youtube_organic_search_retryable_on_429() -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 429
    mock_resp.text = 'rate limited'

    async def _inner() -> list[dict[str, object]]:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            return await youtube_organic_search(
                'q',
                login='u',
                password='p',
            )

    with pytest.raises(RetryableProviderError):
        asyncio.run(_inner())


def test_youtube_organic_search_fatal_on_401() -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 401
    mock_resp.text = 'unauthorized'

    async def _inner() -> list[dict[str, object]]:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            return await youtube_organic_search(
                'q',
                login='u',
                password='p',
            )

    with pytest.raises(FatalProviderError):
        asyncio.run(_inner())


def test_youtube_video_info_uses_video_id_and_live_path() -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = _ok_payload([{'video_id': 'vid1'}])
    mock_post = AsyncMock(return_value=mock_resp)

    async def _inner() -> list[dict[str, object]]:
        with patch('httpx.AsyncClient.post', new=mock_post):
            return await youtube_video_info(
                'vid1',
                login='u',
                password='p',
            )

    items = asyncio.run(_inner())
    assert items[0]['video_id'] == 'vid1'
    url = mock_post.call_args.args[0]
    assert url.endswith('/v3/serp/youtube/video_info/live/advanced')
    body = mock_post.call_args.kwargs['json']
    assert body[0]['video_id'] == 'vid1'


def test_youtube_video_comments_and_subtitles_success() -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = _ok_payload(
        [{'text': 'great video', 'type': 'youtube_comment'}],
    )

    async def _inner() -> tuple[
        list[dict[str, object]],
        list[dict[str, object]],
    ]:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            comments = await youtube_video_comments(
                'vid1',
                login='u',
                password='p',
            )
            subs = await youtube_video_subtitles(
                'vid1',
                login='u',
                password='p',
            )
            return comments, subs

    comments, subs = asyncio.run(_inner())
    assert comments[0]['text'] == 'great video'
    assert subs[0]['text'] == 'great video'


def test_youtube_organic_search_empty_tasks_returns_empty() -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {'status_code': 20000, 'tasks': []}

    async def _inner() -> list[dict[str, object]]:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            return await youtube_organic_search(
                'q',
                login='u',
                password='p',
            )

    assert asyncio.run(_inner()) == []


def test_youtube_organic_search_retryable_on_500() -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = False
    mock_resp.status_code = 500
    mock_resp.text = 'oops'

    async def _inner() -> list[dict[str, object]]:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            return await youtube_organic_search(
                'q',
                login='u',
                password='p',
            )

    with pytest.raises(RetryableProviderError):
        asyncio.run(_inner())


def test_truncate_helpers_cover_edge_branches() -> None:
    from server.apps.generation.clients.dataforseo import (
        _truncate_item,
        _truncate_text,
        _truncate_value,
    )

    assert _truncate_text('abc', 0) == ''
    assert _truncate_text('abc', 2) == 'ab'
    assert _truncate_text('abc', 10) == 'abc'
    nested = _truncate_item(
        {
            'description': 'x' * 50,
            'kids': [{'title': 'y' * 50}, 'plain'],
            'count': 3,
        },
        8,
    )
    assert nested['description'].endswith('...')
    assert nested['count'] == 3
    assert _truncate_value('hi', 10) == 'hi'


def test_youtube_organic_search_task_error_is_fatal() -> None:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        'status_code': 20000,
        'tasks': [
            {
                'status_code': 40100,
                'status_message': 'Auth failed',
                'result': None,
            },
        ],
    }

    async def _inner() -> list[dict[str, object]]:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            return await youtube_organic_search(
                'q',
                login='u',
                password='p',
            )

    with pytest.raises(FatalProviderError, match='Auth failed'):
        asyncio.run(_inner())


def _post_payload(payload: dict[str, object]) -> list[dict[str, object]]:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = payload

    async def _inner() -> list[dict[str, object]]:
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(return_value=mock_resp),
        ):
            return await youtube_organic_search(
                'q',
                login='u',
                password='p',
            )

    return asyncio.run(_inner())


def test_youtube_organic_search_empty_result_returns_empty() -> None:
    assert (
        _post_payload(
            {
                'status_code': 20000,
                'tasks': [{'status_code': 20000, 'result': []}],
            },
        )
        == []
    )


def test_youtube_organic_search_non_list_items_returns_empty() -> None:
    assert (
        _post_payload(
            {
                'status_code': 20000,
                'tasks': [
                    {
                        'status_code': 20000,
                        'result': [{'items': 'not-a-list'}],
                    },
                ],
            },
        )
        == []
    )


def test_youtube_organic_search_reads_subtitles_when_items_missing() -> None:
    items = _post_payload(
        {
            'status_code': 20000,
            'tasks': [
                {
                    'status_code': 20000,
                    'result': [{'subtitles': [{'text': 'hello'}]}],
                },
            ],
        },
    )
    assert items[0]['text'] == 'hello'


def test_youtube_organic_search_null_first_result_returns_empty() -> None:
    assert (
        _post_payload(
            {
                'status_code': 20000,
                'tasks': [{'status_code': 20000, 'result': [None]}],
            },
        )
        == []
    )
