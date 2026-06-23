"""Direct tests for legacy analytics async views."""

import asyncio
import json

import pytest
from django.http import HttpRequest

from server.apps.analytics.views import (
    channel_roi_view,
    channel_stages_view,
    run_cost_view,
)
from server.apps.channels.models import Channel, ChannelKind
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunStatus,
)


@pytest.fixture
def channel(db: None) -> Channel:
    """Channel for legacy view tests."""
    return Channel.objects.create(
        name='Legacy View Channel',
        kind=ChannelKind.LONGFORM,
    )


@pytest.fixture
def run(channel: Channel, db: None) -> PipelineRun:
    """Completed run for legacy view tests."""
    blueprint = PipelineBlueprint.objects.create(
        name='legacy_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic='Legacy test',
        status=RunStatus.COMPLETED,
        total_cost_usd='2.5000',
    )


@pytest.mark.django_db
def test_run_cost_view_direct(run: PipelineRun) -> None:
    """run_cost_view returns JSON cost breakdown."""
    request = HttpRequest()
    response = asyncio.run(run_cost_view(request, str(run.id)))

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data['run_id'] == str(run.id)
    assert 'grand_total_usd' in data


@pytest.mark.django_db
def test_channel_roi_view_direct(channel: Channel) -> None:
    """channel_roi_view returns JSON ROI aggregates."""
    request = HttpRequest()
    response = asyncio.run(channel_roi_view(request, str(channel.id)))

    assert response.status_code == 200
    data = json.loads(response.content)
    assert 'run_count' in data


@pytest.mark.django_db
def test_channel_stages_view_direct(channel: Channel) -> None:
    """channel_stages_view returns stage performance rows."""
    request = HttpRequest()
    response = asyncio.run(channel_stages_view(request, str(channel.id)))

    assert response.status_code == 200
    data = json.loads(response.content)
    assert 'stage_performance' in data
