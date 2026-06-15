"""ASGI streaming views for pipeline events."""

import json
from collections.abc import AsyncIterator

import redis.asyncio as aioredis
from django.conf import settings
from django.http import HttpRequest, JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt

from server.apps.pipelines.services.orchestrator import approve_gate_impl


async def event_stream(run_id: str) -> AsyncIterator[str]:
    """Yield SSE-formatted lines from the pipeline Redis pub/sub channel."""
    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)  # type: ignore[no-untyped-call]
    pubsub = client.pubsub()
    await pubsub.subscribe(f'pipeline:{run_id}')
    try:
        async for message in pubsub.listen():
            if message['type'] == 'message':
                yield f'data: {message["data"]}\n\n'
    finally:
        await pubsub.unsubscribe(f'pipeline:{run_id}')
        await client.aclose()


async def pipeline_events(  # noqa: RUF029
    request: HttpRequest,
    run_id: str,
) -> StreamingHttpResponse:
    """Stream server-sent events for a pipeline run from Redis pub/sub."""
    response = StreamingHttpResponse(
        event_stream(run_id),
        content_type='text/event-stream',
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


@csrf_exempt
async def gate_approve(
    request: HttpRequest,
    run_id: str,
    gate_key: str,
) -> JsonResponse:
    """Handle POST /api/runs/<run_id>/gates/<gate_key>/approve/."""
    try:
        body: dict[str, object] = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    await approve_gate_impl(run_id, gate_key, body)
    return JsonResponse({'status': 'ok'})
