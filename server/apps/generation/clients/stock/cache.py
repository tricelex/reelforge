"""Redis-backed caching for footage provider searches.

Provider quotas are small (Pexels allows 200 requests/hour) while a single
documentary fans out over ~60 scenes. Caching by normalised query means shard
retries, gate swaps, and stage reruns cost no additional quota.
"""

import asyncio
import json
import re
import time
from collections.abc import Callable
from typing import Any

import attrs
import structlog

from server.apps.generation.clients.stock.base import (
    FootageCandidate,
    FootageProvider,
    MediaType,
)
from server.common.redis_client import get_redis

logger = structlog.get_logger(__name__)

_WHITESPACE_RE = re.compile(r'\s+')
_DEFAULT_TTL_S = 86_400
_MAX_CONCURRENT_PER_PROVIDER = 4

# One semaphore per provider name, shared across all shards in this worker
# process. A 60-way scene fan-out would otherwise open 60 simultaneous
# connections to the same provider and trip rate limiting immediately.
_SEMAPHORES: dict[str, asyncio.Semaphore] = {}


def _semaphore(provider_name: str) -> asyncio.Semaphore:
    """Return the shared concurrency limiter for one provider."""
    if provider_name not in _SEMAPHORES:
        _SEMAPHORES[provider_name] = asyncio.Semaphore(
            _MAX_CONCURRENT_PER_PROVIDER,
        )
    return _SEMAPHORES[provider_name]


# Documented free-tier quotas: (max_requests, window_seconds). A long-form
# run can fan out over 100+ scenes, and the concurrency semaphore above only
# bounds how many requests are in flight at once — it does not stop the
# *rate* of requests from exceeding an hourly/per-minute quota. Providers
# without a documented limit get a conservative default.
_RATE_LIMITS: dict[str, tuple[int, float]] = {
    'pexels': (200, 3600.0),
    'pixabay': (100, 60.0),
}
_DEFAULT_RATE_LIMIT: tuple[int, float] = (60, 60.0)


class _TokenBucket:
    """Async token bucket pacing requests to a provider's documented quota."""

    def __init__(
        self,
        capacity: int,
        window_s: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._capacity = float(capacity)
        self._refill_rate = capacity / window_s
        self._tokens = float(capacity)
        self._clock = clock
        self._updated_at = clock()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until one request's worth of quota is available."""
        async with self._lock:
            now = self._clock()
            elapsed = max(0.0, now - self._updated_at)
            self._tokens = min(
                self._capacity,
                self._tokens + elapsed * self._refill_rate,
            )
            self._updated_at = now
            if self._tokens < 1.0:
                wait_s = (1.0 - self._tokens) / self._refill_rate
                await asyncio.sleep(wait_s)
                self._tokens = 0.0
                self._updated_at = self._clock()
            else:
                self._tokens -= 1.0


_BUCKETS: dict[str, _TokenBucket] = {}


def _bucket(provider_name: str) -> _TokenBucket:
    """Return the shared rate limiter for one provider."""
    if provider_name not in _BUCKETS:
        capacity, window_s = _RATE_LIMITS.get(
            provider_name,
            _DEFAULT_RATE_LIMIT,
        )
        _BUCKETS[provider_name] = _TokenBucket(capacity, window_s)
    return _BUCKETS[provider_name]


def normalize_query(query: str) -> str:
    """Return a canonical cache form of a search query."""
    return _WHITESPACE_RE.sub(' ', query.strip().casefold())


def _cache_key(
    provider_name: str,
    query: str,
    media_type: MediaType,
    orientation: str,
    min_width: int,
    limit: int,
) -> str:
    """Build the Redis key for one provider search."""
    normalized = normalize_query(query)
    return (
        f'footage:{provider_name}:{media_type}:'
        f'{orientation}:{min_width}:{limit}:{normalized}'
    )


def _serialize(candidates: list[FootageCandidate]) -> bytes:
    """Encode candidates as a JSON array."""
    payload: list[dict[str, Any]] = []
    for candidate in candidates:
        data = attrs.asdict(candidate)
        data['tags'] = list(data['tags'])
        payload.append(data)
    return json.dumps(payload).encode()


def _validate_rows(rows: object) -> list[dict[str, Any]]:
    """Validate and narrow a decoded cache payload."""
    if not isinstance(rows, list):
        raise TypeError('cached payload is not a list')
    if not all(isinstance(row, dict) for row in rows):
        raise TypeError('cached row is not a dict')
    return rows


def _deserialize(raw: bytes) -> list[FootageCandidate] | None:
    """Decode cached bytes, returning None when the entry is unusable."""
    try:
        rows = _validate_rows(json.loads(raw))
        return [
            FootageCandidate(**{**row, 'tags': tuple(row.get('tags', []))})
            for row in rows
        ]
    except Exception as exc:
        logger.warning('footage_cache_corrupt', error=str(exc))
        return None


async def cached_search(
    provider: FootageProvider,
    query: str,
    *,
    media_type: MediaType,
    orientation: str,
    min_width: int,
    limit: int,
    ttl_s: int = _DEFAULT_TTL_S,
) -> list[FootageCandidate]:
    """Search a provider, reading through a Redis cache."""
    key = _cache_key(
        provider.name,
        query,
        media_type,
        orientation,
        min_width,
        limit,
    )
    redis = get_redis()
    try:
        raw = await redis.get(key)
        if raw:
            cached = _deserialize(raw)
            if cached is not None:
                return cached

        async with _semaphore(provider.name):
            await _bucket(provider.name).acquire()
            results = await provider.search(
                query,
                media_type=media_type,
                orientation=orientation,
                min_width=min_width,
                limit=limit,
            )
        await redis.set(key, _serialize(results), ex=ttl_s)
        return results
    finally:
        await redis.aclose()
