"""Tests for YouTube channel URL parsing and resolve/list helpers."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.generation.clients.youtube_search import (
    list_channel_videos,
    parse_youtube_channel_ref,
    resolve_channel,
)
from server.common.exceptions import FatalProviderError


def test_parse_youtube_channel_handle_url() -> None:
    kind, token = parse_youtube_channel_ref(
        'https://www.youtube.com/@HistoryHub/videos',
    )
    assert kind == 'handle'
    assert token == 'HistoryHub'


def test_parse_youtube_channel_id_url() -> None:
    kind, token = parse_youtube_channel_ref(
        'https://youtube.com/channel/UCabcdefghijklmnopqrstuv',
    )
    assert kind == 'id'
    assert token == 'UCabcdefghijklmnopqrstuv'


def test_parse_youtube_channel_custom_and_user() -> None:
    kind, token = parse_youtube_channel_ref(
        'https://www.youtube.com/c/Veritasium',
    )
    assert kind == 'custom'
    assert token == 'Veritasium'
    kind, token = parse_youtube_channel_ref(
        'https://youtube.com/user/oldschool',
    )
    assert kind == 'username'
    assert token == 'oldschool'


def test_parse_youtube_channel_bare_handle_and_id() -> None:
    kind, token = parse_youtube_channel_ref('@MinutePhysics')
    assert kind == 'handle'
    assert token == 'MinutePhysics'
    channel_id = 'UCabcdefghijklmnopqrstuv'
    kind, token = parse_youtube_channel_ref(channel_id)
    assert kind == 'id'
    assert token == channel_id


def test_parse_youtube_channel_rejects_empty_and_non_youtube() -> None:
    with pytest.raises(ValueError, match='required'):
        parse_youtube_channel_ref('  ')
    with pytest.raises(ValueError, match='Not a YouTube'):
        parse_youtube_channel_ref('https://vimeo.com/123')


def test_resolve_channel_uses_for_handle() -> None:
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        'items': [{'id': 'UChandle1', 'snippet': {'title': 'Hub'}}],
    }
    mock_get = AsyncMock(return_value=fake_resp)

    async def _inner() -> dict[str, object]:
        with patch('httpx.AsyncClient.get', new=mock_get):
            return await resolve_channel(
                'https://youtube.com/@Hub',
                api_key='k',
            )

    result = asyncio.run(_inner())
    assert result['id'] == 'UChandle1'
    assert mock_get.call_args.kwargs['params']['forHandle'] == 'Hub'


def test_resolve_channel_custom_searches_then_fetches_id() -> None:
    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = {
        'items': [{'id': {'channelId': 'UCfromsearch'}}],
    }
    channel_resp = MagicMock()
    channel_resp.status_code = 200
    channel_resp.json.return_value = {
        'items': [{'id': 'UCfromsearch', 'snippet': {'title': 'V'}}],
    }
    mock_get = AsyncMock(side_effect=[search_resp, channel_resp])

    async def _inner() -> dict[str, object]:
        with patch('httpx.AsyncClient.get', new=mock_get):
            return await resolve_channel(
                'https://youtube.com/c/Veritasium',
                api_key='k',
            )

    result = asyncio.run(_inner())
    assert result['id'] == 'UCfromsearch'
    assert mock_get.call_count == 2


def test_resolve_channel_missing_raises_fatal() -> None:
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {'items': []}

    async def _inner() -> dict[str, object]:
        with patch(
            'httpx.AsyncClient.get',
            new=AsyncMock(return_value=fake_resp),
        ):
            return await resolve_channel(
                'https://youtube.com/@ghost',
                api_key='k',
            )

    with pytest.raises(FatalProviderError, match='not found'):
        asyncio.run(_inner())


def test_parse_youtube_channel_rejects_watch_and_empty_path() -> None:
    with pytest.raises(ValueError, match='Could not parse'):
        parse_youtube_channel_ref('https://youtube.com/watch?v=abc')
    with pytest.raises(ValueError, match='Could not parse'):
        parse_youtube_channel_ref('https://youtube.com/')


def test_resolve_channel_username_and_id() -> None:
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        'items': [{'id': 'UCuser1', 'snippet': {'title': 'Old'}}],
    }
    mock_get = AsyncMock(return_value=fake_resp)

    async def _inner() -> dict[str, object]:
        with patch('httpx.AsyncClient.get', new=mock_get):
            by_user = await resolve_channel(
                'https://youtube.com/user/oldschool',
                api_key='k',
            )
            by_id = await resolve_channel(
                'UCabcdefghijklmnopqrstuv',
                api_key='k',
            )
            return {'user': by_user, 'id': by_id}

    result = asyncio.run(_inner())
    assert result['user']['id'] == 'UCuser1'
    assert mock_get.call_args_list[0].kwargs['params']['forUsername'] == (
        'oldschool'
    )
    assert mock_get.call_args_list[1].kwargs['params']['id'] == (
        'UCabcdefghijklmnopqrstuv'
    )


def test_resolve_channel_custom_missing_channel_id_raises() -> None:
    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = {'items': [{'id': {}}]}

    async def _inner() -> dict[str, object]:
        with patch(
            'httpx.AsyncClient.get',
            new=AsyncMock(return_value=search_resp),
        ):
            return await resolve_channel(
                'https://youtube.com/c/Ghost',
                api_key='k',
            )

    with pytest.raises(FatalProviderError, match='not found'):
        asyncio.run(_inner())


def test_parse_youtube_custom_path_without_c_prefix() -> None:
    kind, token = parse_youtube_channel_ref(
        'https://www.youtube.com/Veritasium',
    )
    assert kind == 'custom'
    assert token == 'Veritasium'


def test_resolve_channel_custom_empty_search_raises() -> None:
    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = {'items': []}

    async def _inner() -> dict[str, object]:
        with patch(
            'httpx.AsyncClient.get',
            new=AsyncMock(return_value=search_resp),
        ):
            return await resolve_channel(
                'https://youtube.com/c/Ghost',
                api_key='k',
            )

    with pytest.raises(FatalProviderError, match='not found'):
        asyncio.run(_inner())


def test_list_channel_videos_passes_channel_id_and_order() -> None:
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {'items': [{'id': {'videoId': 'v1'}}]}
    mock_get = AsyncMock(return_value=fake_resp)

    async def _inner() -> list[dict[str, object]]:
        with patch('httpx.AsyncClient.get', new=mock_get):
            return await list_channel_videos(
                'UCabcdefghijklmnopqrstuv',
                api_key='k',
                order='viewCount',
                max_results=10,
            )

    result = asyncio.run(_inner())
    assert result == [{'id': {'videoId': 'v1'}}]
    params = mock_get.call_args.kwargs['params']
    assert params['channelId'] == 'UCabcdefghijklmnopqrstuv'
    assert params['order'] == 'viewCount'
    assert params['type'] == 'video'
