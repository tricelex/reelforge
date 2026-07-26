"""Redis-backed caching for footage provider searches.

Provider quotas are small (Pexels allows 200 requests/hour) while a single
documentary fans out over ~60 scenes. Caching by normalised query means shard
retries, gate swaps, and stage reruns cost no additional quota.
"""

import asyncio
import json
import re
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


def normalize_query(query: str) -> str:
    """Return a canonical cache form of a search query."""
    return _WHITESPACE_RE.sub(' ', query.strip().casefold())


def _cache_key(
    provider_name: str,
    query: str,
    media_type: MediaType,
    orientation: str,
    limit: int,
) -> str:
    """Build the Redis key for one provider search."""
    normalized = normalize_query(query)
    return (
        f'footage:{provider_name}:{media_type}:'
        f'{orientation}:{limit}:{normalized}'
    )


def _serialize(candidates: list[FootageCandidate]) -> bytes:
    """Encode candidates as a JSON array."""
    payload: list[dict[str, Any]] = []
    for candidate in candidates:
        data = attrs.asdict(candidate)
        data['tags'] = list(data['tags'])
        payload.append(data)
    return json.dumps(payload).encode()


def _deserialize(raw: bytes) -> list[FootageCandidate] | None:
    """Decode cached bytes, returning None when the entry is unusable."""
    try:
        rows = json.loads(raw)
        if not isinstance(rows, list):
            raise TypeError('cached payload is not a list')
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError('cached row is not a dict')
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
    key = _cache_key(provider.name, query, media_type, orientation, limit)
    redis = get_redis()
    try:
        raw = await redis.get(key)
        if raw:
            cached = _deserialize(raw)
            if cached is not None:
                return cached

        async with _semaphore(provider.name):
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
