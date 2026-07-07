"""Tests for the niche outlier scan (quota-aware, cached daily)."""

import asyncio
from collections.abc import Coroutine
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import django.utils.timezone as tz
import pytest

from server.apps.channels.models import Channel, ChannelKind, NicheConfig
from server.apps.ideas.models import NicheOutlierScan
from server.apps.ideas.outlier_scan import (
    get_cached_scan,
    run_niche_outlier_scan,
)


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    from asgiref.sync import sync_to_async

    @sync_to_async
    def _close_connections() -> None:
        from django.db import connections

        connections.close_all()

    async def _wrapped() -> Any:
        try:
            return await coro
        finally:
            await _close_connections()

    return asyncio.run(_wrapped())


@pytest.fixture
def niche(db) -> NicheConfig:  # type: ignore[no-untyped-def]
    channel = Channel.objects.create(
        name='Outlier Ch', kind=ChannelKind.LONGFORM,
    )
    return NicheConfig.objects.create(
        channel=channel,
        audience='history buffs',
        angle='ancient empires',
    )


@pytest.mark.django_db(transaction=True)
def test_run_niche_outlier_scan_persists_results(niche: NicheConfig) -> None:
    """A fresh scan calls the YouTube client and writes a NicheOutlierScan row."""
    search_items = [
        {'id': {'videoId': 'vid1'}, 'snippet': {'channelId': 'chan1'}},
    ]
    stats_items = [
        {
            'id': 'vid1',
            'snippet': {
                'title': 'Why Rome Really Fell',
                'channelTitle': 'History Hub',
                'channelId': 'chan1',
                'publishedAt': '2026-06-01T00:00:00Z',
            },
            'statistics': {'viewCount': '2000000'},
        },
    ]
    channel_stats_items = [
        {'id': 'chan1', 'statistics': {'subscriberCount': '50000'}},
    ]

    async def _inner() -> list:
        with (
            patch(
                'server.apps.ideas.outlier_scan.search_videos',
                new=AsyncMock(return_value=search_items),
            ),
            patch(
                'server.apps.ideas.outlier_scan.get_video_statistics',
                new=AsyncMock(return_value=stats_items),
            ),
            patch(
                'server.apps.ideas.outlier_scan.get_channel_statistics',
                new=AsyncMock(return_value=channel_stats_items),
            ),
        ):
            return await run_niche_outlier_scan(niche)

    results = _run(_inner())
    assert len(results) == 1
    assert results[0].video_id == 'vid1'
    assert results[0].outlier_score > 0

    assert NicheOutlierScan.objects.filter(niche=niche).count() == 1


@pytest.mark.django_db
def test_get_cached_scan_returns_none_when_stale_or_missing(
    niche: NicheConfig,
) -> None:
    """get_cached_scan returns None when no scan exists, or the latest is >24h old."""
    assert get_cached_scan(str(niche.id)) is None

    stale = NicheOutlierScan.objects.create(
        niche=niche,
        query='ancient empires',
        results=[
            {
                'video_id': 'v1',
                'title': 't',
                'channel_title': 'c',
                'view_count': 1,
                'published_at': '2026-01-01T00:00:00Z',
                'outlier_score': 1.0,
            },
        ],
    )
    stale.created_at = tz.now() - timedelta(hours=25)
    stale.save(update_fields=['created_at'])

    assert get_cached_scan(str(niche.id)) is None


@pytest.mark.django_db
def test_get_cached_scan_returns_results_within_24h(niche: NicheConfig) -> None:
    """get_cached_scan returns the parsed results of a scan from the last 24h."""
    scan = NicheOutlierScan.objects.create(
        niche=niche,
        query='ancient empires',
        results=[
            {
                'video_id': 'v1',
                'title': 'Fresh',
                'channel_title': 'c',
                'view_count': 100,
                'published_at': '2026-07-01T00:00:00Z',
                'outlier_score': 2.5,
            },
        ],
    )

    assert str(niche.id) in str(scan)

    cached = get_cached_scan(str(niche.id))
    assert cached is not None
    assert cached[0].title == 'Fresh'
