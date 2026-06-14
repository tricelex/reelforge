"""Tests for the pipeline SSE streaming view."""

import asyncio
import json
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def test_event_stream_yields_sse_messages() -> None:
    """event_stream yields SSE-formatted lines for Redis 'message' events."""
    from server.apps.pipelines.views import event_stream  # noqa: PLC0415

    async def _inner() -> None:
        event_data = json.dumps({'type': 'stage.queued', 'stage': 'research'})

        async def _fake_listen():  # noqa: RUF029
            yield {'type': 'subscribe', 'data': 1}
            yield {'type': 'message', 'data': event_data}

        mock_pubsub = MagicMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.listen = _fake_listen
        mock_client = MagicMock()
        mock_client.pubsub.return_value = mock_pubsub
        mock_client.aclose = AsyncMock()

        with patch(
            'server.apps.pipelines.views.aioredis.from_url',
            return_value=mock_client,
        ):
            chunks = [chunk async for chunk in event_stream('fake-run-id')]

        assert len(chunks) == 1
        assert chunks[0].startswith('data: ')
        assert 'stage.queued' in chunks[0]
        mock_pubsub.subscribe.assert_called_once_with('pipeline:fake-run-id')
        mock_pubsub.unsubscribe.assert_called_once_with('pipeline:fake-run-id')
        mock_client.aclose.assert_called_once()

    _run(_inner())


def test_pipeline_events_response_headers() -> None:
    """pipeline_events returns StreamingHttpResponse with SSE headers."""
    from django.test import RequestFactory  # noqa: PLC0415

    from server.apps.pipelines.views import pipeline_events  # noqa: PLC0415

    async def _inner() -> None:
        request = RequestFactory().get('/api/runs/fake-run-id/events/')

        with patch('server.apps.pipelines.views.aioredis.from_url'):
            response = await pipeline_events(request, 'fake-run-id')

        assert response.status_code == 200
        assert response['Content-Type'] == 'text/event-stream'
        assert response['Cache-Control'] == 'no-cache'
        assert response['X-Accel-Buffering'] == 'no'

    _run(_inner())
