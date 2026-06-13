import redis.asyncio as aioredis
from django.conf import settings


def get_redis() -> aioredis.Redis:  # type: ignore[type-arg]
    """Return a configured async Redis client (one per call; callers close it)."""
    return aioredis.from_url(settings.REDIS_URL, decode_responses=False)


async def publish_pipeline_event(run_id: str, data: bytes) -> None:
    """Publish an encoded SSE event to the pipeline Redis channel."""
    client = get_redis()
    await client.publish(f'pipeline:{run_id}', data)
