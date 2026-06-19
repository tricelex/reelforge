"""Tests for analytics API views."""

import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.channels.models import Channel, ChannelKind
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunStatus,
)


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
        total_cost_usd='1.2345',
    )


@pytest.mark.django_db
def test_run_cost_view_returns_200(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """GET /api/analytics/runs/<run_id>/cost/ returns 200 with cost data."""
    resp = dmr_client.get(
        reverse('api:analytics_api:run-cost', kwargs={'run_id': run.id}),
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['run_id'] == str(run.id)
    assert 'grand_total_usd' in data


@pytest.mark.django_db
def test_channel_roi_view_returns_200(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """GET /api/analytics/channels/<channel_id>/roi/ returns 200."""
    resp = dmr_client.get(
        reverse(
            'api:analytics_api:channel-roi',
            kwargs={'channel_id': channel.id},
        ),
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert 'run_count' in data


@pytest.mark.django_db
def test_channel_stages_view_returns_200(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """GET /api/analytics/channels/<channel_id>/stages/ returns 200."""
    resp = dmr_client.get(
        reverse(
            'api:analytics_api:channel-stages',
            kwargs={'channel_id': channel.id},
        ),
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert 'stage_performance' in data
