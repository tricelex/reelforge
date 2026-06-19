"""Tests for pipeline run DMR API."""

from http import HTTPStatus
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
)


@pytest.fixture
def channel(db: None) -> Channel:
    """Longform channel for run API tests."""
    return Channel.objects.create(
        name='Run API Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
    )


@pytest.fixture
def blueprint(db: None) -> PipelineBlueprint:
    """Active longform blueprint."""
    return PipelineBlueprint.objects.create(
        name='longform_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': [{'key': 'research', 'depends_on': []}]},
        is_active=True,
    )


@pytest.fixture
def run(
    channel: Channel,
    blueprint: PipelineBlueprint,
    db: None,
) -> PipelineRun:
    """Existing pipeline run."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='Test topic',
        status=RunStatus.PENDING,
    )


@pytest.mark.django_db
def test_create_run(
    dmr_client: DMRClient,
    channel: Channel,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    """POST /api/runs/ creates a run and returns detail."""
    with patch(
        'server.apps.pipelines.tasks.advance_pipeline.kiq',
        new_callable=AsyncMock,
    ) as mock_kiq:
        response = dmr_client.post(
            reverse('api:pipelines_api:run-collection'),
            data={
                'channel_id': str(channel.id),
                'topic': 'New video idea',
            },
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.CREATED
    data = response.json()
    assert data['topic'] == 'New video idea'
    assert data['channel_id'] == str(channel.id)
    mock_kiq.assert_called_once()


@pytest.mark.django_db
def test_list_runs(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """GET /api/runs/ returns paginated runs."""
    response = dmr_client.get(
        reverse('api:pipelines_api:run-collection'),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data['total'] == 1
    assert len(data['items']) == 1
    assert data['items'][0]['id'] == str(run.id)


@pytest.mark.django_db
def test_get_run_detail(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """GET /api/runs/{id}/ returns full detail."""
    response = dmr_client.get(
        reverse('api:pipelines_api:run-detail', kwargs={'run_id': run.id}),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['id'] == str(run.id)


@pytest.mark.django_db
def test_cancel_run(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """POST /api/runs/{id}/cancel/ cancels the run."""
    with patch(
        'server.apps.pipelines.services.orchestrator.publish_sse',
        new_callable=AsyncMock,
    ):
        response = dmr_client.post(
            reverse('api:pipelines_api:run-cancel', kwargs={'run_id': run.id}),
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    run.refresh_from_db()
    assert run.status == RunStatus.CANCELLED


@pytest.mark.django_db
def test_pause_and_resume_run(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Pause and resume toggles is_paused."""
    with patch(
        'server.apps.pipelines.services.orchestrator.publish_sse',
        new_callable=AsyncMock,
    ):
        pause_resp = dmr_client.post(
            reverse('api:pipelines_api:run-pause', kwargs={'run_id': run.id}),
            headers=auth_headers,
        )

    assert pause_resp.status_code == HTTPStatus.OK
    run.refresh_from_db()
    assert run.is_paused is True

    with patch(
        'server.apps.pipelines.services.orchestrator.advance_pipeline_impl',
        new_callable=AsyncMock,
    ):
        resume_resp = dmr_client.post(
            reverse('api:pipelines_api:run-resume', kwargs={'run_id': run.id}),
            headers=auth_headers,
        )

    assert resume_resp.status_code == HTTPStatus.OK
    run.refresh_from_db()
    assert run.is_paused is False


@pytest.mark.django_db
def test_issue_sse_token(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """POST events/token returns a signed token."""
    response = dmr_client.post(
        reverse(
            'api:pipelines_api:run-events-token',
            kwargs={'run_id': run.id},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert 'token' in data
    assert 'expires_at' in data

    from server.apps.pipelines.services.pipeline_run import (  # noqa: PLC0415
        PipelineRunService,
    )

    assert PipelineRunService.validate_sse_token(data['token'], str(run.id))
