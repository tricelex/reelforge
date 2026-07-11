"""Tests for pipeline run DMR API."""

import uuid
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
    StageExecution,
    StageStatus,
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
def test_create_run_uses_channel_default_blueprint(
    dmr_client: DMRClient,
    channel: Channel,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    """POST /api/runs/ falls back to channel.default_blueprint_name."""
    alt = PipelineBlueprint.objects.create(
        name='longform_alt',
        kind=PipelineKind.LONGFORM,
        graph={'stages': [{'key': 'research', 'depends_on': []}]},
        is_active=True,
    )
    channel.default_blueprint_name = alt.name
    channel.save(update_fields=['default_blueprint_name'])

    with patch('server.apps.pipelines.services.pipeline_run.kiq_task'):
        response = dmr_client.post(
            reverse('api:pipelines_api:run-collection'),
            data={
                'channel_id': str(channel.id),
                'topic': 'Channel default blueprint',
            },
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.CREATED
    assert response.json()['blueprint_name'] == alt.name
    run = PipelineRun.objects.get(id=response.json()['id'])
    assert run.blueprint_id == alt.id


@pytest.mark.django_db
def test_create_run(
    dmr_client: DMRClient,
    channel: Channel,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    """POST /api/runs/ creates a run and returns detail."""
    with patch(
        'server.apps.pipelines.services.pipeline_run.kiq_task',
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

    from server.apps.pipelines.services.pipeline_run import (
        PipelineRunService,
    )

    assert PipelineRunService.validate_sse_token(data['token'], str(run.id))
    assert (
        PipelineRunService.validate_sse_token('bad-token', str(run.id)) is False
    )


@pytest.mark.django_db
def test_create_run_idempotency(
    dmr_client: DMRClient,
    channel: Channel,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    """Repeated POST with same idempotency key returns cached run."""
    from django.core.cache import cache

    cache_key = f'idem-run-{uuid.uuid4()}'
    headers = {**auth_headers, 'Idempotency-Key': cache_key}
    with patch(
        'server.apps.pipelines.services.pipeline_run.kiq_task',
    ) as mock_kiq:
        first = dmr_client.post(
            reverse('api:pipelines_api:run-collection'),
            data={'channel_id': str(channel.id), 'topic': 'Idempotent topic'},
            headers=headers,
        )
        assert first.status_code == HTTPStatus.CREATED
        cached_id = cache.get(f'idempotency:{cache_key}')
        assert cached_id is not None
        second = dmr_client.post(
            reverse('api:pipelines_api:run-collection'),
            data={'channel_id': str(channel.id), 'topic': 'Idempotent topic'},
            headers=headers,
        )

    assert second.status_code == HTTPStatus.CREATED
    assert first.json()['id'] == second.json()['id']
    mock_kiq.assert_called_once()


@pytest.mark.django_db
def test_pipeline_run_service_idempotency(
    channel: Channel,
    blueprint: PipelineBlueprint,
) -> None:
    """Service create returns cached run for repeated idempotency keys."""
    from unittest.mock import MagicMock

    from server.apps.pipelines.logic.value_objects import RunCreatePayload
    from server.apps.pipelines.services.pipeline_run import PipelineRunService
    from server.common.events import EventBus

    service = PipelineRunService(MagicMock(spec=EventBus))
    payload = RunCreatePayload(
        channel_id=str(channel.id),
        topic='Service idempotent topic',
    )
    idem_key = f'svc-idem-{uuid.uuid4()}'
    with patch(
        'server.apps.pipelines.services.pipeline_run.kiq_task',
    ) as mock_kiq:
        first = service.create(payload, idempotency_key=idem_key)
        second = service.create(payload, idempotency_key=idem_key)

    assert first.id == second.id
    mock_kiq.assert_called_once()


@pytest.mark.django_db
def test_create_run_requires_topic_or_source(
    dmr_client: DMRClient,
    channel: Channel,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    """POST run without topic or source_id returns 400."""
    response = dmr_client.post(
        reverse('api:pipelines_api:run-collection'),
        data={'channel_id': str(channel.id)},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_create_run_bad_channel(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """POST with unknown channel returns 400."""
    response = dmr_client.post(
        reverse('api:pipelines_api:run-collection'),
        data={'channel_id': str(uuid.uuid4()), 'topic': 'Missing channel'},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_create_run_blueprint_not_found(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """POST returns 400 when no active blueprint exists."""
    response = dmr_client.post(
        reverse('api:pipelines_api:run-collection'),
        data={'channel_id': str(channel.id), 'topic': 'No blueprint'},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_list_runs_filters_and_cursor(
    dmr_client: DMRClient,
    channel: Channel,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    """GET supports status/channel filters and cursor pagination."""
    other_channel = Channel.objects.create(
        name='Other Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
    )
    PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='Pending run',
        status=RunStatus.PENDING,
    )
    PipelineRun.objects.create(
        channel=other_channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='Completed run',
        status=RunStatus.COMPLETED,
    )

    filtered = dmr_client.get(
        (
            f'{reverse("api:pipelines_api:run-collection")}'
            f'?status={RunStatus.COMPLETED}&channel={other_channel.id}&limit=1'
        ),
        headers=auth_headers,
    )
    assert filtered.status_code == HTTPStatus.OK
    filtered_body = filtered.json()
    assert filtered_body['total'] == 1
    assert filtered_body['items'][0]['channel_id'] == str(other_channel.id)
    assert filtered_body['next_cursor'] is None

    page_one = dmr_client.get(
        f'{reverse("api:pipelines_api:run-collection")}?limit=1',
        headers=auth_headers,
    )
    assert page_one.status_code == HTTPStatus.OK
    page_one_body = page_one.json()
    assert page_one_body['next_cursor'] is not None

    page_two = dmr_client.get(
        (
            f'{reverse("api:pipelines_api:run-collection")}'
            f'?limit=1&cursor={page_one_body["next_cursor"]}'
        ),
        headers=auth_headers,
    )
    assert page_two.status_code == HTTPStatus.OK
    assert page_two.json()['items'][0]['id'] != page_one_body['items'][0]['id']


@pytest.mark.django_db
def test_get_run_detail_includes_stage_error(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """GET detail exposes error payload for failed stages."""
    StageExecution.objects.create(
        run=run,
        stage_key='clip_transcribe',
        status=StageStatus.FAILED,
        attempt=0,
        error={
            'type': 'RuntimeError',
            'message': 'whisperx failed: module not found',
            'retryable': False,
        },
    )

    response = dmr_client.get(
        reverse('api:pipelines_api:run-detail', kwargs={'run_id': run.id}),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    stage = response.json()['stages'][0]
    assert stage['error']['type'] == 'RuntimeError'
    assert 'whisperx failed' in stage['error']['message']
    assert stage['error']['retryable'] is False


@pytest.mark.django_db
def test_get_run_detail_includes_latest_stage_attempts(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """GET detail deduplicates stages to the latest parent attempt."""
    StageExecution.objects.create(
        run=run,
        stage_key='research',
        status=StageStatus.FAILED,
        attempt=0,
    )
    StageExecution.objects.create(
        run=run,
        stage_key='research',
        status=StageStatus.SUCCEEDED,
        attempt=1,
    )

    response = dmr_client.get(
        reverse('api:pipelines_api:run-detail', kwargs={'run_id': run.id}),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    stages = response.json()['stages']
    assert len(stages) == 1
    assert stages[0]['attempt'] == 1
    assert stages[0]['status'] == StageStatus.SUCCEEDED


@pytest.mark.django_db(transaction=True)
def test_rerun_stage(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """POST stage rerun stales downstream and enqueues a fresh attempt."""
    import server.apps.pipelines.stages.dummy  # noqa: F401

    blueprint = PipelineBlueprint.objects.create(
        name='rerun_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {'key': 'dummy_a', 'depends_on': []},
                {'key': 'dummy_b', 'depends_on': ['dummy_a']},
            ],
        },
        is_active=True,
    )
    rerun_run = PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='Rerun topic',
        status=RunStatus.COMPLETED,
    )
    StageExecution.objects.create(
        run=rerun_run,
        stage_key='dummy_a',
        status=StageStatus.SUCCEEDED,
        attempt=0,
    )
    StageExecution.objects.create(
        run=rerun_run,
        stage_key='dummy_b',
        status=StageStatus.SUCCEEDED,
        attempt=0,
    )

    with (
        patch('server.apps.pipelines.services.pipeline_run.kiq_task') as mock_kiq,
        patch(
            'server.apps.pipelines.services.orchestrator.publish_sse',
            new_callable=AsyncMock,
        ),
    ):
        response = dmr_client.post(
            reverse(
                'api:pipelines_api:stage-rerun',
                kwargs={'run_id': rerun_run.id, 'stage_key': 'dummy_a'},
            ),
            data={'shard_indices': None},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    mock_kiq.assert_called_once()
    rerun_stage = next(
        s for s in response.json()['stages'] if s['stage_key'] == 'dummy_a'
    )
    assert rerun_stage['attempt'] == 1
    assert rerun_stage['status'] == StageStatus.QUEUED
    downstream = StageExecution.objects.get(
        run=rerun_run,
        stage_key='dummy_b',
    )
    assert downstream.status == StageStatus.STALE
    rerun_run.refresh_from_db()
    assert rerun_run.status == RunStatus.RUNNING
