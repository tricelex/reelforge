"""Tests for the gate approval API endpoint."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from django.test import AsyncClient

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
def channel(db):
    """Create a LONGFORM review-mode channel with a single gate."""
    return Channel.objects.create(
        name='Gate API Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
        gates=['final_gate'],
    )


@pytest.fixture
def blueprint(db):
    """Create a LONGFORM pipeline blueprint with an empty stage graph."""
    return PipelineBlueprint.objects.create(
        name='gate_api_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )


@pytest.fixture
def run(channel, blueprint):
    """Create a pipeline run in AWAITING_REVIEW status."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic='Gate API test',
        status=RunStatus.AWAITING_REVIEW,
    )


@pytest.fixture
def gate_execution(run):
    """Create a running stage execution for the final_gate stage."""
    return StageExecution.objects.create(
        run=run,
        stage_key='final_gate',
        status=StageStatus.RUNNING,
        input_hash='',
    )


@pytest.mark.django_db(transaction=True)
def test_gate_approve_endpoint(run, gate_execution):
    """POST to gate approve endpoint calls approve_gate_impl and returns 200."""
    client = AsyncClient()
    body = json.dumps({'thumbnail_asset_id': None, 'schedule_at': None})

    async def _run_request():
        with patch(
            'server.apps.pipelines.views.approve_gate_impl',
            new=AsyncMock(),
        ) as mock_approve:
            resp = await client.post(
                f'/api/runs/{run.id}/gates/final_gate/approve/',
                data=body,
                content_type='application/json',
            )
            return resp, mock_approve

    resp, mock_approve = asyncio.run(_run_request())

    assert resp.status_code == 200
    mock_approve.assert_called_once_with(
        str(run.id),
        'final_gate',
        {'thumbnail_asset_id': None, 'schedule_at': None},
    )


@pytest.mark.django_db(transaction=True)
def test_gate_approve_invalid_json(run):
    """POST with invalid JSON body returns 400."""
    client = AsyncClient()

    async def _run_request():
        return await client.post(
            f'/api/runs/{run.id}/gates/final_gate/approve/',
            data='not json',
            content_type='application/json',
        )

    resp = asyncio.run(_run_request())
    assert resp.status_code == 400
