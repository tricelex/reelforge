"""Tests for analytics API views."""

import asyncio
from collections.abc import Coroutine
from decimal import Decimal
from typing import Any

import pytest
from django.test import AsyncClient

from server.apps.channels.models import Channel, ChannelKind
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunStatus,
)


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine synchronously, closing DB connections on exit."""
    from asgiref.sync import sync_to_async  # noqa: PLC0415

    @sync_to_async
    def _close() -> None:
        from django.db import connections  # noqa: PLC0415

        connections.close_all()

    async def _wrapped() -> Any:
        try:
            return await coro
        finally:
            await _close()

    return asyncio.run(_wrapped())


@pytest.fixture
def channel(db: None) -> Channel:
    """Test channel for analytics view tests."""
    return Channel.objects.create(
        name='View Test Channel',
        kind=ChannelKind.LONGFORM,
    )


@pytest.fixture
def run(channel: Channel, db: None) -> PipelineRun:
    """Completed pipeline run for analytics view tests."""
    bp = PipelineBlueprint.objects.create(
        name='view_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={'stages': []},
        topic='View test',
        status=RunStatus.COMPLETED,
        total_cost_usd=Decimal('1.2345'),
    )


@pytest.mark.django_db(transaction=True)
def test_run_cost_view_returns_200(run: PipelineRun) -> None:
    """GET /api/analytics/runs/<run_id>/cost/ returns 200 with cost data."""
    client = AsyncClient()

    async def _inner() -> None:
        resp = await client.get(f'/api/analytics/runs/{run.id}/cost/')
        assert resp.status_code == 200
        data = resp.json()
        assert data['run_id'] == str(run.id)
        assert 'grand_total_usd' in data

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_channel_roi_view_returns_200(channel: Channel) -> None:
    """GET /api/analytics/channels/<channel_id>/roi/ returns 200."""
    client = AsyncClient()

    async def _inner() -> None:
        resp = await client.get(f'/api/analytics/channels/{channel.id}/roi/')
        assert resp.status_code == 200
        data = resp.json()
        assert 'run_count' in data

    _run(_inner())


@pytest.mark.django_db(transaction=True)
def test_channel_stages_view_returns_200(channel: Channel) -> None:
    """GET /api/analytics/channels/<channel_id>/stages/ returns 200."""
    client = AsyncClient()

    async def _inner() -> None:
        resp = await client.get(f'/api/analytics/channels/{channel.id}/stages/')
        assert resp.status_code == 200
        data = resp.json()
        assert 'stage_performance' in data

    _run(_inner())
