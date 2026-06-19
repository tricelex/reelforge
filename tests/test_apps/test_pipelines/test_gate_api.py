"""Tests for the gate approval API endpoint."""

from unittest.mock import AsyncMock, patch

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
def channel(db: None) -> Channel:
    """Create a LONGFORM review-mode channel with a single gate."""
    return Channel.objects.create(
        name='Gate API Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
        gates=['final_gate'],
    )


@pytest.fixture
def blueprint(db: None) -> PipelineBlueprint:
    """Create a LONGFORM pipeline blueprint with an empty stage graph."""
    return PipelineBlueprint.objects.create(
        name='gate_api_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )


@pytest.fixture
def run(channel: Channel, blueprint: PipelineBlueprint) -> PipelineRun:
    """Create a pipeline run in AWAITING_REVIEW status."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic='Gate API test',
        status=RunStatus.AWAITING_REVIEW,
    )


@pytest.fixture
def gate_execution(run: PipelineRun) -> StageExecution:
    """Create a running stage execution for the final_gate stage."""
    return StageExecution.objects.create(
        run=run,
        stage_key='final_gate',
        status=StageStatus.RUNNING,
        input_hash='',
    )


@pytest.mark.django_db(transaction=True)
def test_gate_approve_endpoint(
    dmr_client: DMRClient,
    run: PipelineRun,
    gate_execution: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """POST to gate approve endpoint calls approve_gate_impl and returns 200."""
    with patch(
        'server.apps.pipelines.api.views.approve_gate_impl',
        new=AsyncMock(return_value=None),
    ) as mock_approve:
        resp = dmr_client.post(
            reverse(
                'api:pipelines_api:gate-approve',
                kwargs={'run_id': run.id, 'gate_key': 'final_gate'},
            ),
            data={'thumbnail_asset_id': None, 'schedule_at': None},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    mock_approve.assert_called_once()


@pytest.mark.django_db(transaction=True)
def test_gate_approve_requires_auth(
    dmr_client: DMRClient,
    run: PipelineRun,
) -> None:
    """Gate approve returns 401 without JWT."""
    resp = dmr_client.post(
        reverse(
            'api:pipelines_api:gate-approve',
            kwargs={'run_id': run.id, 'gate_key': 'final_gate'},
        ),
        data={'thumbnail_asset_id': None},
    )
    assert resp.status_code == 401
