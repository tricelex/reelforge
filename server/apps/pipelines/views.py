"""ASGI streaming views for pipeline events."""

from collections.abc import AsyncIterator

import redis.asyncio as aioredis
from django.conf import settings
from django.http import HttpRequest, StreamingHttpResponse


async def event_stream(run_id: str) -> AsyncIterator[str]:
    """Yield SSE-formatted lines from the pipeline Redis pub/sub channel."""
    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
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
    request: HttpRequest, run_id: str,
) -> StreamingHttpResponse:
    """Stream server-sent events for a pipeline run from Redis pub/sub."""
    response = StreamingHttpResponse(
        event_stream(run_id), content_type='text/event-stream',
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response
