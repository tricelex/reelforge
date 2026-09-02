"""Tests for NexLevService video-record and search-cache methods."""

import asyncio
import hashlib
import json
from unittest.mock import AsyncMock, patch

import pytest
from django.utils import timezone

from server.apps.nexlev.logic import constants
from server.apps.nexlev.models import NexLevSearchCacheEntry, NexLevVideoRecord
from server.apps.nexlev.services import NexLevService


@pytest.mark.django_db(transaction=True)
def test_get_video_details_fetches_when_missing() -> None:
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_video_details',
            new=AsyncMock(return_value={'id': 'v1', 'title': 'X'}),
        ) as mock_call:
            result = await service.get_video_details('v1')
            return result, mock_call

    result, mock_call = asyncio.run(_inner())
    assert result.id == 'v1'
    mock_call.assert_awaited_once()
    record = NexLevVideoRecord.objects.get(video_id='v1')
    assert record.quota_spent == constants.QUOTA_COST_VIDEO_DETAILS


@pytest.mark.django_db(transaction=True)
def test_get_video_details_uses_fresh_record() -> None:
    NexLevVideoRecord.objects.create(
        video_id='v1',
        details={'id': 'v1', 'title': 'Cached'},
        details_fetched_at=timezone.now(),
    )
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_video_details',
            new=AsyncMock(),
        ) as mock_call:
            result = await service.get_video_details('v1')
            return result, mock_call

    result, mock_call = asyncio.run(_inner())
    assert result.title == 'Cached'
    mock_call.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
def test_get_video_transcript_fetches_when_missing() -> None:
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_video_transcript',
            new=AsyncMock(
                return_value=[{'startMs': '0', 'endMs': '100'}],
            ),
        ) as mock_call:
            result = await service.get_video_transcript('v1')
            return result, mock_call

    result, mock_call = asyncio.run(_inner())
    assert result[0].start_ms == '0'
    mock_call.assert_awaited_once()
    record = NexLevVideoRecord.objects.get(video_id='v1')
    assert record.quota_spent == constants.QUOTA_COST_VIDEO_TRANSCRIPT


@pytest.mark.django_db(transaction=True)
def test_get_video_transcript_uses_fresh_record() -> None:
    NexLevVideoRecord.objects.create(
        video_id='v1',
        transcript=[{'startMs': '5', 'endMs': '105'}],
        transcript_fetched_at=timezone.now(),
    )
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_video_transcript',
            new=AsyncMock(),
        ) as mock_call:
            result = await service.get_video_transcript('v1')
            return result, mock_call

    result, mock_call = asyncio.run(_inner())
    assert result[0].start_ms == '5'
    mock_call.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
def test_get_video_comments_fetches_when_missing() -> None:
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_video_comments',
            new=AsyncMock(
                return_value=[{'commentId': 'c1', 'textDisplay': 'hi'}],
            ),
        ) as mock_call:
            result = await service.get_video_comments('v1')
            return result, mock_call

    result, mock_call = asyncio.run(_inner())
    assert result[0].comment_id == 'c1'
    mock_call.assert_awaited_once()
    record = NexLevVideoRecord.objects.get(video_id='v1')
    assert record.quota_spent == constants.QUOTA_COST_VIDEO_COMMENTS


@pytest.mark.django_db(transaction=True)
def test_get_video_comments_uses_fresh_record() -> None:
    NexLevVideoRecord.objects.create(
        video_id='v1',
        comments=[{'commentId': 'c2', 'textDisplay': 'cached'}],
        comments_fetched_at=timezone.now(),
    )
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_video_comments',
            new=AsyncMock(),
        ) as mock_call:
            result = await service.get_video_comments('v1')
            return result, mock_call

    result, mock_call = asyncio.run(_inner())
    assert result[0].text_display == 'cached'
    mock_call.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
def test_search_youtube_caches_by_query() -> None:
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.search_youtube',
            new=AsyncMock(return_value=[{'type': 'video', 'title': 'Hit'}]),
        ) as mock_call:
            first = await service.search_youtube('rome history')
            second = await service.search_youtube('rome history')
            return first, second, mock_call

    first, second, mock_call = asyncio.run(_inner())
    assert first[0].title == 'Hit'
    assert second[0].title == 'Hit'
    mock_call.assert_awaited_once()
    cache_key = hashlib.sha256(
        json.dumps(
            {'query': 'rome history', 'type': None},
            sort_keys=True,
        ).encode(),
    ).hexdigest()
    assert NexLevSearchCacheEntry.objects.filter(cache_key=cache_key).exists()
