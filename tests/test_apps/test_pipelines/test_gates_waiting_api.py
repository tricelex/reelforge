"""Tests for gates waiting API."""

from http import HTTPStatus

import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.channels.models import Channel, ChannelKind, PublishMode
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunStatus,
    StageExecution,
    StageStatus,
)


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    return Channel.objects.create(
        name='Gate Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
        gates=['final_gate'],
    )


@pytest.fixture
def waiting_run(channel: Channel, db) -> PipelineRun:  # type: ignore[no-untyped-def]
    blueprint = PipelineBlueprint.objects.create(
        name='longform_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic='Waiting topic',
        status=RunStatus.AWAITING_REVIEW,
        total_cost_usd='3.5000',
    )
    StageExecution.objects.create(
        run=run,
        stage_key='final_gate',
        status=StageStatus.RUNNING,
        attempt=0,
    )
    return run


@pytest.mark.django_db
def test_gates_waiting_list(
    dmr_client: DMRClient,
    waiting_run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """GET /api/gates/waiting/ returns armed gate queue rows."""
    response = dmr_client.get(
        reverse('api:pipelines_api:gates-waiting'),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['total'] == 1
    row = body['items'][0]
    assert row['run_id'] == str(waiting_run.id)
    assert row['gate_key'] == 'final_gate'
    assert row['topic'] == 'Waiting topic'
    assert row['spent_usd'] == '3.5000'


@pytest.mark.django_db
def test_gates_waiting_ignores_unarmed_gate(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """Runs at gates not in channel.gates are excluded."""
    blueprint = PipelineBlueprint.objects.create(
        name='longform_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic='Unarmed',
        status=RunStatus.AWAITING_REVIEW,
    )
    StageExecution.objects.create(
        run=run,
        stage_key='storyboard_gate',
        status=StageStatus.RUNNING,
        attempt=0,
    )
    response = dmr_client.get(
        reverse('api:pipelines_api:gates-waiting'),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['total'] == 0
