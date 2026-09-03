"""Tests for the NexLev value objects and HTTP client."""

import asyncio

import httpx
import msgspec
import pytest

from server.apps.nexlev.clients import nexlev_client
from server.apps.nexlev.logic.value_objects import NexLevChannelAbout
from server.common.exceptions import FatalProviderError, RetryableProviderError

_API_KEY = 'test-key'
_BASE_URL = 'https://prod.dashboard.nexlev.io'


def test_channel_about_decodes_camel_case_json() -> None:
    raw = {
        'channelId': 'UC123',
        'title': 'Test Channel',
        'description': 'A channel',
        'subscriberCount': 1000,
        'videosCount': 42,
        'viewCount': 99999,
    }
    result = msgspec.convert(raw, type=NexLevChannelAbout)
    assert result.channel_id == 'UC123'
    assert result.subscriber_count == 1000
    assert result.videos_count == 42


def _patch_get(
    monkeypatch: pytest.MonkeyPatch,
    response: httpx.Response,
) -> None:
    async def _fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return response

    monkeypatch.setattr(httpx.AsyncClient, 'get', _fake_get)


def _patch_post(
    monkeypatch: pytest.MonkeyPatch,
    response: httpx.Response,
) -> None:
    async def _fake_post(
        self: httpx.AsyncClient,
        url: str,
        *,
        json: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return response

    monkeypatch.setattr(httpx.AsyncClient, 'post', _fake_post)


def test_get_channel_about_returns_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(
        monkeypatch,
        httpx.Response(200, json={'channelId': 'UC1', 'title': 'X'}),
    )

    result = asyncio.run(
        nexlev_client.get_channel_about(
            'UC1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert result['channelId'] == 'UC1'


def test_get_channel_about_raises_fatal_on_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(monkeypatch, httpx.Response(401, json={'error': 'nope'}))

    with pytest.raises(FatalProviderError):
        asyncio.run(
            nexlev_client.get_channel_about(
                'UC1',
                api_key=_API_KEY,
                base_url=_BASE_URL,
            ),
        )


def test_get_channel_about_raises_retryable_on_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(monkeypatch, httpx.Response(429, json={'error': 'quota'}))

    with pytest.raises(RetryableProviderError):
        asyncio.run(
            nexlev_client.get_channel_about(
                'UC1',
                api_key=_API_KEY,
                base_url=_BASE_URL,
            ),
        )


def test_get_channel_analytics_flattens_about_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_post(
        monkeypatch,
        httpx.Response(
            200,
            json=[
                {
                    'about': {
                        'subscriberCount': 10,
                        'viewCount': 20,
                        'videoCount': 3,
                        'country': 'US',
                    },
                    'categories': ['Tech'],
                    'tags': ['gadgets'],
                },
            ],
        ),
    )

    result = asyncio.run(
        nexlev_client.get_channel_analytics(
            'UC1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert result['subscriberCount'] == 10
    assert result['categories'] == ['Tech']


def test_get_similar_channels_flattens_about_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_post(
        monkeypatch,
        httpx.Response(
            200,
            json={
                'data': [
                    {
                        'about': {'channelId': 'UC2', 'channelName': 'Rival'},
                        'similarityScore': 72,
                    },
                ],
            },
        ),
    )

    result = asyncio.run(
        nexlev_client.get_similar_channels(
            'UC1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert result[0]['channelId'] == 'UC2'
    assert result[0]['similarityScore'] == 72


def test_get_video_details_unwraps_list_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(
        monkeypatch,
        httpx.Response(200, json=[{'id': 'v1', 'title': 'Video'}]),
    )

    result = asyncio.run(
        nexlev_client.get_video_details(
            'v1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert result['id'] == 'v1'


def test_get_video_details_raises_fatal_when_no_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NexLev returns 200 + [] when it has no data for a video_id."""
    _patch_get(monkeypatch, httpx.Response(200, json=[]))

    with pytest.raises(FatalProviderError):
        asyncio.run(
            nexlev_client.get_video_details(
                'missing-video',
                api_key=_API_KEY,
                base_url=_BASE_URL,
            ),
        )


def test_create_channel_analysis_job_unwraps_list_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(
        monkeypatch,
        httpx.Response(200, json=[{'job_id': 'job-1', 'channel_id': 'UC1'}]),
    )

    job_id = asyncio.run(
        nexlev_client.create_channel_analysis_job(
            'UC1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert job_id == 'job-1'


def test_get_channel_analysis_result_returns_none_when_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(
        monkeypatch,
        httpx.Response(200, json={'status': 'processing', 'progress': 40}),
    )

    result = asyncio.run(
        nexlev_client.get_channel_analysis_result(
            'job-1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert result is None


def test_get_channel_analysis_result_returns_data_when_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(
        monkeypatch,
        httpx.Response(
            200,
            json={'status': 'completed', 'result': {'channel_id': 'UC1'}},
        ),
    )

    result = asyncio.run(
        nexlev_client.get_channel_analysis_result(
            'job-1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert result is not None
    assert result['result']['channel_id'] == 'UC1'


def test_get_channel_about_raises_fatal_on_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(monkeypatch, httpx.Response(404, json={'error': 'missing'}))

    with pytest.raises(FatalProviderError):
        asyncio.run(
            nexlev_client.get_channel_about(
                'UC1',
                api_key=_API_KEY,
                base_url=_BASE_URL,
            ),
        )


def test_get_channel_about_raises_retryable_on_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(monkeypatch, httpx.Response(500, json={'error': 'boom'}))

    with pytest.raises(RetryableProviderError):
        asyncio.run(
            nexlev_client.get_channel_about(
                'UC1',
                api_key=_API_KEY,
                base_url=_BASE_URL,
            ),
        )


def test_get_channel_about_raises_fatal_on_unexpected_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(monkeypatch, httpx.Response(302))

    with pytest.raises(FatalProviderError):
        asyncio.run(
            nexlev_client.get_channel_about(
                'UC1',
                api_key=_API_KEY,
                base_url=_BASE_URL,
            ),
        )


def test_get_channel_outliers_returns_outliers_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(
        monkeypatch,
        httpx.Response(
            200,
            json={
                'outliers': [{'videoId': 'v1', 'title': 'Hit'}],
                'totalOutliers': 1,
            },
        ),
    )

    result = asyncio.run(
        nexlev_client.get_channel_outliers(
            'UC1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert result == [{'videoId': 'v1', 'title': 'Hit'}]


def test_get_niche_overview_returns_raw_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_post(
        monkeypatch,
        httpx.Response(
            200,
            json={'originalChannelId': 'UC1', 'similarChannels': []},
        ),
    )

    result = asyncio.run(
        nexlev_client.get_niche_overview(
            'UC1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert result['originalChannelId'] == 'UC1'


def test_get_video_transcript_unwraps_list_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(
        monkeypatch,
        httpx.Response(
            200,
            json=[
                {
                    'id': 'v1',
                    'transcript': [{'startMs': '0', 'endMs': '100'}],
                },
            ],
        ),
    )

    result = asyncio.run(
        nexlev_client.get_video_transcript(
            'v1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert result == [{'startMs': '0', 'endMs': '100'}]


def test_get_video_comments_returns_comment_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(
        monkeypatch,
        httpx.Response(
            200,
            json={
                'commentsCount': '1',
                'data': [{'commentId': 'c1', 'textDisplay': 'hi'}],
            },
        ),
    )

    result = asyncio.run(
        nexlev_client.get_video_comments(
            'v1',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert result == [{'commentId': 'c1', 'textDisplay': 'hi'}]


def test_search_youtube_returns_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get(
        monkeypatch,
        httpx.Response(
            200,
            json={
                'results': [{'type': 'video', 'title': 'Hit'}],
                'resultCount': 1,
            },
        ),
    )

    result = asyncio.run(
        nexlev_client.search_youtube(
            'rome',
            api_key=_API_KEY,
            base_url=_BASE_URL,
        ),
    )
    assert result == [{'type': 'video', 'title': 'Hit'}]


def test_search_youtube_passes_search_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        captured['params'] = params
        return httpx.Response(200, json={'results': []})

    monkeypatch.setattr(httpx.AsyncClient, 'get', _fake_get)

    asyncio.run(
        nexlev_client.search_youtube(
            'rome',
            api_key=_API_KEY,
            base_url=_BASE_URL,
            search_type='video',
        ),
    )
    assert captured['params'] == {'query': 'rome', 'type': 'video'}
