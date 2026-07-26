"""Tests for footage search caching."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.generation.clients.stock.base import FootageCandidate
from server.apps.generation.clients.stock.cache import (
    cached_search,
    normalize_query,
)


def _candidate() -> FootageCandidate:
    return FootageCandidate(
        provider='pexels',
        external_id='1',
        media_type='video',
        download_url='https://e.test/v.mp4',
        thumb_url='https://e.test/t.jpg',
        source_page_url='https://e.test/p',
        width=1920,
        height=1080,
        duration_s=10.0,
        license='pexels',
        license_url='',
        author='A',
        attribution_required=False,
        title='t',
        tags=(),
    )


def test_normalize_query_is_stable() -> None:
    """Case and whitespace differences produce the same cache key."""
    assert normalize_query('  Ocean   WAVES ') == normalize_query('ocean waves')


@pytest.mark.anyio
async def test_cache_miss_calls_provider_and_stores() -> None:
    """On a miss the provider runs and the result is written to Redis."""
    provider = MagicMock()
    provider.name = 'pexels'
    provider.search = AsyncMock(return_value=[_candidate()])

    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.aclose = AsyncMock()

    with patch(
        'server.apps.generation.clients.stock.cache.get_redis',
        return_value=redis,
    ):
        results = await cached_search(
            provider,
            'ocean waves',
            media_type='video',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )

    assert len(results) == 1
    provider.search.assert_awaited_once()
    redis.set.assert_awaited_once()
    redis.aclose.assert_awaited_once()


@pytest.mark.anyio
async def test_cache_hit_skips_the_provider() -> None:
    """A cached payload is returned without spending provider quota."""
    provider = MagicMock()
    provider.name = 'pexels'
    provider.search = AsyncMock()

    payload = json.dumps([attrs_asdict_of(_candidate())]).encode()
    redis = MagicMock()
    redis.get = AsyncMock(return_value=payload)
    redis.set = AsyncMock()
    redis.aclose = AsyncMock()

    with patch(
        'server.apps.generation.clients.stock.cache.get_redis',
        return_value=redis,
    ):
        results = await cached_search(
            provider,
            'ocean waves',
            media_type='video',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )

    assert len(results) == 1
    provider.search.assert_not_awaited()
    redis.aclose.assert_awaited_once()


def attrs_asdict_of(candidate: FootageCandidate) -> dict[str, object]:
    """Serialise a candidate the way the cache does."""
    import attrs

    data = attrs.asdict(candidate)
    data['tags'] = list(data['tags'])
    return data


@pytest.mark.parametrize(
    'raw_payload',
    [b'not json', b'{}', b'[1]'],
)
@pytest.mark.anyio
async def test_corrupt_cache_entry_falls_back_to_provider(
    raw_payload: bytes,
) -> None:
    """Unusable cached bytes must not break the search."""
    provider = MagicMock()
    provider.name = 'pexels'
    provider.search = AsyncMock(return_value=[_candidate()])

    redis = MagicMock()
    redis.get = AsyncMock(return_value=raw_payload)
    redis.set = AsyncMock()
    redis.aclose = AsyncMock()

    with patch(
        'server.apps.generation.clients.stock.cache.get_redis',
        return_value=redis,
    ):
        results = await cached_search(
            provider,
            'ocean waves',
            media_type='video',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )

    assert len(results) == 1
    provider.search.assert_awaited_once()
    redis.aclose.assert_awaited_once()
