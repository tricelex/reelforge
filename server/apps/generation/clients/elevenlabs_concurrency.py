"""Limit concurrent ElevenLabs API calls across worker processes.

ElevenLabs enforces per-workspace concurrency (2–15 depending on plan).
TTS fans out one task per script chapter; with ``max-async-tasks=4`` a single
worker can exceed the limit immediately.  A Redis-backed slot pool enforces
the global cap; an in-process semaphore is the fallback when Redis is down.
"""

import asyncio
import random
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from django.conf import settings

from server.common.exceptions import RetryableProviderError

logger = structlog.get_logger(__name__)

_KEY = 'elevenlabs:semaphore'
_SLOT_TTL_S = 300
_POLL_INTERVAL_S = 0.25
_ACQUIRE_TIMEOUT_S = 120

_local_sem: asyncio.Semaphore | None = None

_ACQUIRE_LUA = """
local cutoff = tonumber(ARGV[3]) - tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff)
if redis.call('ZCARD', KEYS[1]) < tonumber(ARGV[1]) then
    redis.call('ZADD', KEYS[1], ARGV[3], ARGV[2])
    redis.call('EXPIRE', KEYS[1], math.ceil(tonumber(ARGV[4]) / 1000))
    return 1
end
return 0
"""

_RELEASE_LUA = """
return redis.call('ZREM', KEYS[1], ARGV[1])
"""


def _max_concurrent() -> int:
    return max(1, int(getattr(settings, 'ELEVENLABS_MAX_CONCURRENT', 2)))


def _get_local_semaphore() -> asyncio.Semaphore:
    global _local_sem
    if _local_sem is None:
        _local_sem = asyncio.Semaphore(_max_concurrent())
    return _local_sem


async def _acquire_redis_slot(token: str, limit: int) -> bool:
    from server.common.redis_client import get_redis  # noqa: PLC0415

    redis = get_redis()
    try:
        deadline = time.monotonic() + _ACQUIRE_TIMEOUT_S
        while time.monotonic() < deadline:
            now_ms = int(time.time() * 1000)
            acquired = await redis.eval(
                _ACQUIRE_LUA,
                1,
                _KEY,
                limit,
                token,
                now_ms,
                _SLOT_TTL_S * 1000,
            )
            if acquired:
                return True
            await asyncio.sleep(
                _POLL_INTERVAL_S + random.uniform(0, 0.1),
            )
        return False
    finally:
        await redis.aclose()


async def _release_redis_slot(token: str) -> None:
    from server.common.redis_client import get_redis  # noqa: PLC0415

    redis = get_redis()
    try:
        await redis.eval(_RELEASE_LUA, 1, _KEY, token)
    finally:
        await redis.aclose()


@asynccontextmanager
async def elevenlabs_slot() -> AsyncIterator[None]:
    """Acquire a concurrency slot before calling ElevenLabs."""
    limit = _max_concurrent()
    token = str(uuid.uuid4())

    try:
        acquired = await _acquire_redis_slot(token, limit)
    except Exception as exc:
        logger.warning(
            'elevenlabs_redis_semaphore_fallback',
            error=str(exc),
        )
        async with _get_local_semaphore():
            yield
        return

    if not acquired:
        raise RetryableProviderError(
            'ElevenLabs concurrency slot timeout',
            provider='elevenlabs',
            status_code=429,
        )

    try:
        yield
    finally:
        try:
            await _release_redis_slot(token)
        except Exception as exc:
            logger.warning(
                'elevenlabs_redis_semaphore_release_failed',
                error=str(exc),
            )
