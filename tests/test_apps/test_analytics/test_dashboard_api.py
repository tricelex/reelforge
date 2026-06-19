"""Tests for operator dashboard API."""

import django.utils.timezone as tz
import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.channels.models import Channel, ChannelKind
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunStatus,
    StageExecution,
    StageStatus,
)
from server.apps.publishing.models import PublishJob, PublishStatus


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    """Channel for dashboard tests."""
    return Channel.objects.create(
        name='Dashboard Channel',
        kind=ChannelKind.LONGFORM,
    )


@pytest.fixture
def run(channel: Channel, db) -> PipelineRun:  # type: ignore[no-untyped-def]
    """Run awaiting review."""
    bp = PipelineBlueprint.objects.create(
        name='dash_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={'stages': []},
        topic='Dashboard test',
        status=RunStatus.AWAITING_REVIEW,
        total_cost_usd='2.50',
    )


@pytest.mark.django_db
def test_dashboard_summary(
    dmr_client: DMRClient,
    run: PipelineRun,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """GET /api/dashboard/ returns in-flight counts and publish calendar."""
    StageExecution.objects.create(
        run=run,
        stage_key='final_gate',
        status=StageStatus.RUNNING,
        attempt=0,
    )
    PublishJob.objects.create(
        run=run,
        channel=channel,
        status=PublishStatus.PENDING,
        schedule_at=tz.datetime(2026, 7, 1, 18, 0, tzinfo=tz.UTC),
    )

    response = dmr_client.get(
        reverse('api:analytics_root:dashboard'),
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body['runs_in_flight'] >= 1
    assert body['gates_waiting'] >= 1
    assert 'spend_today_usd' in body
    assert len(body['publish_scheduled']) == 1


@pytest.mark.django_db
def test_dashboard_non_list_calendar(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """Dashboard coerces non-list publish_scheduled values to []."""
    from unittest.mock import patch

    with patch(
        'server.apps.analytics.api.views.selectors.get_dashboard',
        return_value={
            'runs_in_flight': 0,
            'gates_waiting': 0,
            'spend_today_usd': '0.00',
            'publish_scheduled': 'invalid',
        },
    ):
        response = dmr_client.get(
            reverse('api:analytics_root:dashboard'),
            headers=auth_headers,
        )

    assert response.status_code == 200
    assert response.json()['publish_scheduled'] == []
