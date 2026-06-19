"""ASGI streaming views for pipeline events."""

from collections.abc import AsyncIterator

import redis.asyncio as aioredis
from django.conf import settings
from django.http import HttpRequest, HttpResponse, StreamingHttpResponse

from server.apps.pipelines.services.pipeline_run import PipelineRunService


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
) -> StreamingHttpResponse | HttpResponse:
    """Stream server-sent events for a pipeline run from Redis pub/sub."""
    token = request.GET.get('token', '')
    if not PipelineRunService.validate_sse_token(token, run_id):
        return HttpResponse(status=401)

    response = StreamingHttpResponse(
        event_stream(run_id),
        content_type='text/event-stream',
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response
