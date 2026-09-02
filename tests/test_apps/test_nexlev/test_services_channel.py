"""Tests for NexLevService channel-section methods."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from django.utils import timezone

from server.apps.nexlev.logic import constants
from server.apps.nexlev.models import NexLevChannelRecord
from server.apps.nexlev.services import NexLevService


@pytest.mark.django_db(transaction=True)
def test_get_channel_about_fetches_when_missing() -> None:
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_channel_about',
            new=AsyncMock(
                return_value={
                    'channelId': 'UC1',
                    'title': 'X',
                    'subscriberCount': 10,
                    'videosCount': 2,
                    'viewCount': 100,
                },
            ),
        ) as mock_call:
            result = await service.get_channel_about('UC1')
            return result, mock_call

    result, mock_call = asyncio.run(_inner())
    assert result.channel_id == 'UC1'
    mock_call.assert_awaited_once()
    record = NexLevChannelRecord.objects.get(channel_id='UC1')
    assert record.about_fetched_at is not None
    assert record.quota_spent == constants.QUOTA_COST_ABOUT


@pytest.mark.django_db(transaction=True)
def test_get_channel_about_uses_fresh_record_without_calling_api() -> None:
    NexLevChannelRecord.objects.create(
        channel_id='UC1',
        about={
            'channelId': 'UC1',
            'title': 'Cached',
            'subscriberCount': 5,
            'videosCount': 1,
            'viewCount': 50,
        },
        about_fetched_at=timezone.now(),
    )
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_channel_about',
            new=AsyncMock(),
        ) as mock_call:
            result = await service.get_channel_about('UC1')
            return result, mock_call

    result, mock_call = asyncio.run(_inner())
    assert result.title == 'Cached'
    mock_call.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
def test_get_channel_about_refetches_when_stale() -> None:
    stale_at = timezone.now() - constants.ABOUT_STALE_AFTER - timedelta(days=1)
    NexLevChannelRecord.objects.create(
        channel_id='UC1',
        about={'channelId': 'UC1', 'title': 'Old'},
        about_fetched_at=stale_at,
    )
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_channel_about',
            new=AsyncMock(return_value={'channelId': 'UC1', 'title': 'New'}),
        ) as mock_call:
            result = await service.get_channel_about('UC1')
            return result, mock_call

    result, mock_call = asyncio.run(_inner())
    assert result.title == 'New'
    mock_call.assert_awaited_once()


@pytest.mark.django_db(transaction=True)
def test_get_channel_about_force_refresh_ignores_freshness() -> None:
    NexLevChannelRecord.objects.create(
        channel_id='UC1',
        about={'channelId': 'UC1', 'title': 'Cached'},
        about_fetched_at=timezone.now(),
    )
    service = NexLevService()

    async def _inner() -> object:
        with patch(
            'server.apps.nexlev.services.nexlev_client.get_channel_about',
            new=AsyncMock(return_value={'channelId': 'UC1', 'title': 'Forced'}),
        ) as mock_call:
            result = await service.get_channel_about(
                'UC1',
                force_refresh=True,
            )
            return result, mock_call

    result, mock_call = asyncio.run(_inner())
    assert result.title == 'Forced'
    mock_call.assert_awaited_once()
