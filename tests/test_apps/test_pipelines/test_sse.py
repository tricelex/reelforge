"""Tests for the pipeline SSE streaming endpoint."""

import json
import uuid
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.core.signing import TimestampSigner
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.channels.models import Channel, ChannelKind, PublishMode
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunStatus,
)
from server.apps.pipelines.services.pipeline_run import PipelineRunService


@pytest.fixture
def channel(db: None) -> Channel:
    """Longform channel for SSE tests."""
    return Channel.objects.create(
        name='SSE Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
    )


@pytest.fixture
def blueprint(db: None) -> PipelineBlueprint:
    """Active longform blueprint for SSE tests."""
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
    """Pipeline run for SSE tests."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot=blueprint.graph,
        topic='SSE test run',
        status=RunStatus.RUNNING,
    )


def _signed_token(run_id: str) -> str:
    return TimestampSigner(salt='pipeline-sse-token').sign(run_id)


@pytest.mark.django_db
def test_produce_pipeline_events_yields_typed_sse(run: PipelineRun) -> None:
    """produce_pipeline_events parses Redis payloads into SSEvent objects."""
    from server.apps.pipelines.api.events_views import produce_pipeline_events
    from server.apps.pipelines.logic.sse_events import RunAdvancedEvent

    async def _inner() -> None:
        event_data = json.dumps(
            {'type': 'run.advanced', 'states': {'research': 'running'}},
        )

        async def _fake_listen():
            yield {'type': 'subscribe', 'data': 1}
            yield {'type': 'message', 'data': event_data.encode('utf-8')}
            yield {'type': 'message', 'data': event_data}

        mock_pubsub = MagicMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.listen = _fake_listen
        mock_client = MagicMock()
        mock_client.pubsub.return_value = mock_pubsub
        mock_client.aclose = AsyncMock()

        with patch(
            'server.apps.pipelines.api.events_views.get_redis',
            return_value=mock_client,
        ):
            events = [
                event
                async for event in produce_pipeline_events(str(run.id))
            ]

        assert len(events) == 2
        assert isinstance(events[0].data, RunAdvancedEvent)
        assert isinstance(events[1].data, RunAdvancedEvent)
        assert events[0].data.states == {'research': 'running'}
        mock_pubsub.subscribe.assert_called_once_with(f'pipeline:{run.id}')
        mock_pubsub.unsubscribe.assert_called_once_with(f'pipeline:{run.id}')
        mock_client.aclose.assert_called_once()

    import asyncio

    asyncio.run(_inner())


@pytest.mark.django_db
def test_produce_pipeline_events_emits_ping_when_idle(
    run: PipelineRun,
) -> None:
    """Idle Redis listen yields a comment-only ping keepalive."""
    import asyncio

    from server.apps.pipelines.api.events_views import produce_pipeline_events

    async def _inner() -> None:
        async def _fake_listen():
            await asyncio.sleep(3600)
            yield {'type': 'message', 'data': b'{}'}
            return
            yield  # pragma: no cover

        mock_pubsub = MagicMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.listen = _fake_listen
        mock_client = MagicMock()
        mock_client.pubsub.return_value = mock_pubsub
        mock_client.aclose = AsyncMock()

        with (
            patch(
                'server.apps.pipelines.api.events_views.get_redis',
                return_value=mock_client,
            ),
            patch(
                'server.apps.pipelines.api.events_views._SSE_PING_SECONDS',
                0.01,
            ),
        ):
            agen = produce_pipeline_events(str(run.id))
            event = await agen.__anext__()
            await agen.aclose()

        assert event.comment == 'ping'
        assert event.data is None
        mock_pubsub.unsubscribe.assert_called_once()
        mock_client.aclose.assert_called_once()

    asyncio.run(_inner())


@pytest.mark.django_db
def test_run_events_disables_dmr_builtin_pings(run: PipelineRun) -> None:
    """RunEventsController opts out of DMR's orphan-prone ping race."""
    from server.apps.pipelines.api.events_views import RunEventsController

    assert RunEventsController.streaming_ping_seconds is None


@pytest.mark.django_db
def test_run_events_response_headers(run: PipelineRun) -> None:
    """GET events returns StreamingHttpResponse with SSE headers."""
    from django.test import AsyncRequestFactory

    from server.apps.pipelines.api.events_views import RunEventsController

    async def _inner() -> None:
        token = _signed_token(str(run.id))
        request = AsyncRequestFactory().get(
            f'/api/runs/{run.id}/events/?token={token}',
        )
        with patch('server.apps.pipelines.api.events_views.get_redis'):
            response = await RunEventsController.as_view()(
                request,
                run_id=run.id,
            )

        assert response.status_code == HTTPStatus.OK
        assert response['Content-Type'] == 'text/event-stream'
        assert response['Cache-Control'] == 'no-cache'
        assert response['X-Accel-Buffering'] == 'no'

    import asyncio

    asyncio.run(_inner())


@pytest.mark.django_db
def test_run_events_rejects_invalid_token(
    dmr_client: DMRClient,
    run: PipelineRun,
) -> None:
    """GET events returns 401 without a valid token."""
    response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-events',
            kwargs={'run_id': run.id},
        ),
        query_params={'token': 'bad-token'},
    )

    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
def test_run_events_rejects_missing_token(
    dmr_client: DMRClient,
    run: PipelineRun,
) -> None:
    """GET events returns 422 when the token query param is missing."""
    response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-events',
            kwargs={'run_id': run.id},
        ),
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_validate_sse_token_helper(run: PipelineRun) -> None:
    """Signed tokens remain valid for the matching run id."""
    token = _signed_token(str(run.id))
    assert PipelineRunService.validate_sse_token(token, str(run.id))
    assert (
        PipelineRunService.validate_sse_token('bad-token', str(run.id)) is False
    )
    assert (
        PipelineRunService.validate_sse_token(
            token,
            str(uuid.uuid4()),
        )
        is False
    )


@pytest.mark.django_db
def test_openapi_includes_sse_endpoint(client) -> None:
    """OpenAPI schema documents the pipeline SSE stream."""
    import json

    from django.urls import reverse

    response = client.get(reverse('openapi_json'))
    schema = json.loads(response.content)
    operation = schema['paths']['/api/runs/{run_id}/events/']['get']
    path_item = schema['paths']['/api/runs/{run_id}/events/']
    param_names = {
        param['name']
        for param in (
            *path_item.get('parameters', []),
            *operation.get('parameters', []),
        )
    }

    assert 'Pipeline Runs' in operation['tags']
    assert 'token' in param_names
    stream_content = operation['responses']['200']['content']['text/event-stream']
    assert 'schema' in stream_content or 'itemSchema' in stream_content
