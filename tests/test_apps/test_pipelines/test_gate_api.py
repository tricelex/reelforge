"""Tests for the gate approval API endpoint."""

from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

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
    """POST to gate approve endpoint calls orchestrator sync and returns 200."""
    with (
        patch(
            'server.apps.pipelines.services.orchestrator.advance_pipeline_impl',
            new=AsyncMock(return_value=None),
        ),
        patch(
            'server.apps.pipelines.services.orchestrator._approve_gate_sync',
        ) as mock_sync,
    ):
        resp = dmr_client.post(
            reverse(
                'api:pipelines_api:gate-approve',
                kwargs={'run_id': run.id, 'gate_key': 'final_gate'},
            ),
            data={'thumbnail_asset_id': None, 'schedule_at': None},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    mock_sync.assert_called_once()


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


@pytest.mark.django_db(transaction=True)
def test_gate_approve_thumbnail_and_schedule(
    dmr_client: DMRClient,
    run: PipelineRun,
    gate_execution: StageExecution,
    auth_headers: dict[str, str],
) -> None:
    """Gate approve passes thumbnail_asset_id and schedule_at to orchestrator."""
    thumb_id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
    schedule = '2026-08-15T12:00:00+00:00'

    with (
        patch(
            'server.apps.pipelines.services.orchestrator.advance_pipeline_impl',
            new=AsyncMock(return_value=None),
        ),
        patch(
            'server.apps.pipelines.services.orchestrator._approve_gate_sync',
        ) as mock_sync,
    ):
        resp = dmr_client.post(
            reverse(
                'api:pipelines_api:gate-approve',
                kwargs={'run_id': run.id, 'gate_key': 'final_gate'},
            ),
            data={
                'thumbnail_asset_id': thumb_id,
                'schedule_at': schedule,
            },
            headers=auth_headers,
        )

    assert resp.status_code == 200
    mock_sync.assert_called_once_with(
        str(run.id),
        'final_gate',
        {'thumbnail_asset_id': thumb_id, 'schedule_at': schedule},
    )


@pytest.mark.django_db(transaction=True)
def test_clip_approval_gate_syncs_candidates(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """Clip gate approval syncs candidate statuses via canonical pipelines route."""
    from server.apps.channels.models import (
        ChannelKind,
        PublishMode,
    )
    from server.apps.clips.models import ClipCandidate
    from server.apps.pipelines.models import PipelineKind

    channel = Channel.objects.create(
        name='Clip Gate Channel',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
        gates=['clip_approval_gate'],
    )
    blueprint = PipelineBlueprint.objects.create(
        name='clip_gate_v1',
        kind=PipelineKind.CLIPPING,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic='Clip gate test',
        status=RunStatus.AWAITING_REVIEW,
    )
    candidate = ClipCandidate.objects.create(
        run=run,
        start_sec=0.0,
        end_sec=30.0,
        title='Gate Clip',
    )
    StageExecution.objects.create(
        run=run,
        stage_key='clip_approval_gate',
        status=StageStatus.RUNNING,
        input_hash='',
    )
    approved_ids = [str(candidate.id)]

    with (
        patch(
            'server.apps.pipelines.services.orchestrator.advance_pipeline_impl',
            new=AsyncMock(return_value=None),
        ),
        patch(
            'server.apps.pipelines.services.orchestrator._approve_gate_sync',
        ) as mock_sync,
    ):
        resp = dmr_client.post(
            reverse(
                'api:pipelines_api:gate-approve',
                kwargs={'run_id': run.id, 'gate_key': 'clip_approval_gate'},
            ),
            data={'approved_candidate_ids': approved_ids},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data['status'] == 'ok'
    assert data['approved_count'] == 1
    mock_sync.assert_called_once()
    candidate.refresh_from_db()
    assert candidate.status == 'APPROVED'


@pytest.mark.django_db
def test_gate_approve_non_list_candidates_skips_sync(run: PipelineRun) -> None:
    """Non-list approved_candidate_ids skips clip sync branch."""
    from server.apps.pipelines.api.views import RunGateApproveController
    from server.apps.pipelines.logic.value_objects import GateApprovePayload

    controller = RunGateApproveController()
    controller.kwargs = {
        'run_id': str(run.id),
        'gate_key': 'clip_approval_gate',
    }
    mock_clips = MagicMock()
    payload = GateApprovePayload(approved_candidate_ids=['id-1'])

    with (
        patch.object(controller, 'resolve', return_value=mock_clips),
        patch(
            'server.apps.pipelines.api.views._payload_to_dict',
            return_value={'approved_candidate_ids': 'not-a-list'},
        ),
        patch(
            'server.apps.pipelines.services.orchestrator._approve_gate_sync',
        ),
        patch(
            'server.apps.pipelines.services.orchestrator.advance_pipeline_impl',
            new=AsyncMock(),
        ),
    ):
        result = controller.post(parsed_body=payload)

    assert result.approved_count is None
    mock_clips.sync_gate_candidates.assert_not_called()
