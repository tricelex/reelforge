from __future__ import annotations

import json
import logging
from collections.abc import Generator

import redis
from django.conf import settings

logger = logging.getLogger("reelforge.clipping.sse")

_redis_client: redis.Redis = redis.from_url(settings.REDIS_URL)


def emit_job_event(job_id: str, event_type: str, data: dict) -> None:
    """Publish a structured event to the Redis pub/sub channel for a clipping job.

    Called from Celery tasks after any state transition. Silently logs on failure
    so a Redis outage never breaks the task itself.
    """
    try:
        payload = json.dumps({"type": event_type, "job_id": job_id, **data})
        _redis_client.publish(f"clipping:job:{job_id}", payload)
    except Exception as exc:
        logger.warning(
            "Failed to emit SSE job event",
            extra={"job_id": job_id, "event_type": event_type, "error": str(exc)},
        )


def job_event_stream(job_id: str) -> Generator[str, None, None]:
    """Subscribe to a job's Redis channel and yield SSE-formatted event strings.

    Intended to be used as the content generator for a StreamingHttpResponse.
    Blocks until the client disconnects or the Redis connection drops.
    """
    pubsub = _redis_client.pubsub()
    pubsub.subscribe(f"clipping:job:{job_id}")
    try:
        yield "event: connected\ndata: {}\n\n"
        for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                yield f"data: {data}\n\n"
    finally:
        pubsub.unsubscribe(f"clipping:job:{job_id}")
        pubsub.close()
