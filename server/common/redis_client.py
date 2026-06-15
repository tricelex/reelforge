"""Async Redis client helpers."""

import redis.asyncio as aioredis
from django.conf import settings


def get_redis() -> aioredis.Redis:
    """Return a configured async Redis client; callers must close it."""
    return aioredis.from_url(  # type: ignore[no-untyped-call, no-any-return]
        settings.REDIS_URL,
        decode_responses=False,
    )


async def publish_pipeline_event(run_id: str, data: bytes) -> None:
    """Publish an encoded SSE event to the pipeline Redis channel."""
    client = get_redis()
    await client.publish(f'pipeline:{run_id}', data)
