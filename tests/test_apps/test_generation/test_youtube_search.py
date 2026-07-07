"""Tests for the YouTube search/outlier client."""

from server.apps.generation.clients.youtube_search import compute_outlier_score


def test_compute_outlier_score_views_exceed_subscribers() -> None:
    """A video with 5x its channel's subscriber count in views scores > 1.0."""
    score = compute_outlier_score(
        view_count=500_000,
        subscriber_count=100_000,
        days_since_publish=10,
    )
    assert score > 1.0


def test_compute_outlier_score_zero_subscribers_does_not_divide_by_zero() -> None:
    score = compute_outlier_score(
        view_count=1000,
        subscriber_count=0,
        days_since_publish=1,
    )
    assert score >= 0.0


def test_compute_outlier_score_recent_video_scores_higher_than_old() -> None:
    """Same views/subs ratio, but the more recent video scores higher (velocity)."""
    recent = compute_outlier_score(
        view_count=10_000, subscriber_count=10_000, days_since_publish=2,
    )
    old = compute_outlier_score(
        view_count=10_000, subscriber_count=10_000, days_since_publish=200,
    )
    assert recent > old


def test_search_videos_returns_items() -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from server.apps.generation.clients.youtube_search import search_videos

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {'items': [{'id': {'videoId': 'abc'}}]}

    async def _inner() -> list:
        with patch(
            'httpx.AsyncClient.get',
            new=AsyncMock(return_value=fake_resp),
        ):
            return await search_videos('roman empire', api_key='key123')

    result = asyncio.run(_inner())
    assert result == [{'id': {'videoId': 'abc'}}]


def test_get_video_statistics_empty_ids_returns_empty_without_request() -> None:
    import asyncio

    from server.apps.generation.clients.youtube_search import (
        get_video_statistics,
    )

    result = asyncio.run(get_video_statistics([], api_key='key'))
    assert result == []


def test_search_videos_passes_published_after() -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from server.apps.generation.clients.youtube_search import search_videos

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {'items': []}
    mock_get = AsyncMock(return_value=fake_resp)

    async def _inner() -> list:
        with patch('httpx.AsyncClient.get', new=mock_get):
            return await search_videos(
                'q', api_key='k', published_after='2026-01-01T00:00:00Z',
            )

    result = asyncio.run(_inner())
    assert result == []
    assert mock_get.call_args.kwargs['params']['publishedAfter'] == (
        '2026-01-01T00:00:00Z'
    )


def test_get_video_statistics_returns_items() -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from server.apps.generation.clients.youtube_search import (
        get_video_statistics,
    )

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {'items': [{'id': 'v1'}]}

    async def _inner() -> list:
        with patch('httpx.AsyncClient.get', new=AsyncMock(return_value=fake_resp)):
            return await get_video_statistics(['v1'], api_key='k')

    assert asyncio.run(_inner()) == [{'id': 'v1'}]


def test_get_channel_statistics_empty_ids_returns_empty() -> None:
    import asyncio

    from server.apps.generation.clients.youtube_search import (
        get_channel_statistics,
    )

    assert asyncio.run(get_channel_statistics([], api_key='k')) == []


def test_get_channel_statistics_returns_items() -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from server.apps.generation.clients.youtube_search import (
        get_channel_statistics,
    )

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {'items': [{'id': 'c1'}]}

    async def _inner() -> list:
        with patch('httpx.AsyncClient.get', new=AsyncMock(return_value=fake_resp)):
            return await get_channel_statistics(['c1'], api_key='k')

    assert asyncio.run(_inner()) == [{'id': 'c1'}]


def test_classify_response_raises_retryable_on_503() -> None:
    from unittest.mock import MagicMock

    import pytest

    from server.apps.generation.clients.youtube_search import _classify_response
    from server.common.exceptions import RetryableProviderError

    resp = MagicMock()
    resp.status_code = 503
    with pytest.raises(RetryableProviderError):
        _classify_response(resp)


def test_classify_response_raises_fatal_on_403() -> None:
    from unittest.mock import MagicMock

    import pytest

    from server.apps.generation.clients.youtube_search import _classify_response
    from server.common.exceptions import FatalProviderError

    resp = MagicMock()
    resp.status_code = 403
    resp.text = 'forbidden'
    with pytest.raises(FatalProviderError):
        _classify_response(resp)
