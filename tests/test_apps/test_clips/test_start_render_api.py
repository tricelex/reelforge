"""Tests for POST /runs/{run_id}/start-render/."""

from http import HTTPStatus
from unittest.mock import patch

import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.clips.logic.constants import CandidateStatus
from server.apps.clips.models import ClipCandidate
from server.apps.pipelines.models import RunStatus, StageExecution, StageStatus


@pytest.fixture
def gate_run(db):  # type: ignore[no-untyped-def]
    from server.apps.channels.models import (
        Channel,
        ChannelKind,
        PublishMode,
    )
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
    )

    channel = Channel.objects.create(
        name='Start Render Channel',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )
    blueprint = PipelineBlueprint.objects.create(
        name='clipping_v1',
        kind=PipelineKind.CLIPPING,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic='https://youtube.com/watch?v=start-render',
        status=RunStatus.AWAITING_REVIEW,
    )
    StageExecution.objects.create(
        run=run,
        stage_key='clip_approval_gate',
        status=StageStatus.NEEDS_INPUT,
        input_hash='',
    )
    return run


@pytest.mark.django_db(transaction=True)
def test_start_render_resumes_pipeline(
    dmr_client: DMRClient,
    gate_run: object,
    auth_headers: dict[str, str],
) -> None:
    """POST start-render approves the gate and advances the pipeline."""
    candidate = ClipCandidate.objects.create(
        run=gate_run,  # type: ignore[arg-type]
        start_sec=0.0,
        end_sec=30.0,
        title='Render Me',
        status=CandidateStatus.APPROVED,
    )

    with (
        patch(
            'server.apps.pipelines.services.orchestrator._approve_gate_sync',
        ) as mock_sync,
        patch(
            'server.apps.clips.services.kiq_advance_pipeline',
        ),
    ):
        response = dmr_client.post(
            reverse(
                'clips:start_render',
                kwargs={'run_id': gate_run.id},  # type: ignore[attr-defined]
            ),
            data={},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data['status'] == 'approved'
    assert data['approved_count'] == 1
    mock_sync.assert_called_once()
    candidate.refresh_from_db()
    assert candidate.status == CandidateStatus.APPROVED


@pytest.mark.django_db
def test_start_render_with_explicit_candidate_ids(
    dmr_client: DMRClient,
    gate_run: object,
    auth_headers: dict[str, str],
) -> None:
    """POST start-render accepts explicit approved_candidate_ids."""
    candidate = ClipCandidate.objects.create(
        run=gate_run,  # type: ignore[arg-type]
        start_sec=0.0,
        end_sec=30.0,
        title='Explicit Render',
    )

    with (
        patch(
            'server.apps.pipelines.services.orchestrator._approve_gate_sync',
        ),
        patch(
            'server.apps.clips.services.kiq_advance_pipeline',
        ),
    ):
        response = dmr_client.post(
            reverse(
                'clips:start_render',
                kwargs={'run_id': gate_run.id},  # type: ignore[attr-defined]
            ),
            data={'approved_candidate_ids': [str(candidate.id)]},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['approved_count'] == 1
    candidate.refresh_from_db()
    assert candidate.status == CandidateStatus.APPROVED


@pytest.mark.django_db
def test_start_render_rejects_when_no_candidates_approved(
    dmr_client: DMRClient,
    gate_run: object,
    auth_headers: dict[str, str],
) -> None:
    """POST start-render returns 400 when no candidates are approved."""
    ClipCandidate.objects.create(
        run=gate_run,  # type: ignore[arg-type]
        start_sec=0.0,
        end_sec=30.0,
        title='Still Proposed',
        status=CandidateStatus.PROPOSED,
    )

    response = dmr_client.post(
        reverse(
            'clips:start_render',
            kwargs={'run_id': gate_run.id},  # type: ignore[attr-defined]
        ),
        data={},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.fixture
def running_run(db):  # type: ignore[no-untyped-def]
    from server.apps.channels.models import (
        Channel,
        ChannelKind,
        PublishMode,
    )
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        RunStatus,
    )

    channel = Channel.objects.create(
        name='Running Channel',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )
    blueprint = PipelineBlueprint.objects.create(
        name='clipping_v1',
        kind=PipelineKind.CLIPPING,
        graph={'stages': []},
    )
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic='https://youtube.com/watch?v=running',
        status=RunStatus.RUNNING,
    )


@pytest.mark.django_db
def test_start_render_rejects_when_gate_not_parked(
    dmr_client: DMRClient,
    running_run: object,
    auth_headers: dict[str, str],
) -> None:
    """POST start-render returns 409 when the run is not at the gate."""
    ClipCandidate.objects.create(
        run=running_run,  # type: ignore[arg-type]
        start_sec=0.0,
        end_sec=30.0,
        title='Running Run',
        status=CandidateStatus.APPROVED,
    )

    response = dmr_client.post(
        reverse(
            'clips:start_render',
            kwargs={'run_id': running_run.id},  # type: ignore[attr-defined]
        ),
        data={},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.CONFLICT
