"""Tests for footage search caching."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.generation.clients.stock.base import FootageCandidate
from server.apps.generation.clients.stock.cache import (
    _TokenBucket,
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
async def test_cache_key_separates_minimum_widths() -> None:
    """Searches with different width floors use separate cache entries."""
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
        for min_width in (1280, 1920):
            await cached_search(
                provider,
                'ocean waves',
                media_type='video',
                orientation='landscape',
                min_width=min_width,
                limit=3,
            )

    cache_keys = [call.args[0] for call in redis.get.await_args_list]
    assert cache_keys[0] != cache_keys[1]
    assert ':1280:' in cache_keys[0]
    assert ':1920:' in cache_keys[1]


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


@pytest.mark.anyio
async def test_cached_search_acquires_rate_limit_token_on_miss() -> None:
    """A cache miss consumes one rate-limit token before hitting the API."""
    provider = MagicMock()
    provider.name = 'pexels'
    provider.search = AsyncMock(return_value=[_candidate()])

    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.aclose = AsyncMock()

    bucket = MagicMock()
    bucket.acquire = AsyncMock()

    with (
        patch(
            'server.apps.generation.clients.stock.cache.get_redis',
            return_value=redis,
        ),
        patch(
            'server.apps.generation.clients.stock.cache._bucket',
            return_value=bucket,
        ),
    ):
        await cached_search(
            provider,
            'ocean waves',
            media_type='video',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )

    bucket.acquire.assert_awaited_once()


@pytest.mark.anyio
async def test_cached_search_skips_rate_limit_token_on_hit() -> None:
    """A cache hit must not spend rate-limit quota."""
    provider = MagicMock()
    provider.name = 'pexels'
    provider.search = AsyncMock()

    payload = json.dumps([attrs_asdict_of(_candidate())]).encode()
    redis = MagicMock()
    redis.get = AsyncMock(return_value=payload)
    redis.set = AsyncMock()
    redis.aclose = AsyncMock()

    bucket = MagicMock()
    bucket.acquire = AsyncMock()

    with (
        patch(
            'server.apps.generation.clients.stock.cache.get_redis',
            return_value=redis,
        ),
        patch(
            'server.apps.generation.clients.stock.cache._bucket',
            return_value=bucket,
        ),
    ):
        await cached_search(
            provider,
            'ocean waves',
            media_type='video',
            orientation='landscape',
            min_width=1280,
            limit=3,
        )

    bucket.acquire.assert_not_awaited()


class TestTokenBucket:
    """Tests for the per-provider rate limiter."""

    @pytest.mark.anyio
    async def test_allows_up_to_capacity_without_sleep(self) -> None:
        """Acquiring within capacity never sleeps."""
        bucket = _TokenBucket(capacity=2, window_s=60.0, clock=lambda: 0.0)
        with patch('asyncio.sleep', new=AsyncMock()) as sleep:
            await bucket.acquire()
            await bucket.acquire()
        sleep.assert_not_awaited()

    @pytest.mark.anyio
    async def test_sleeps_for_the_refill_wait_once_exhausted(self) -> None:
        """A call beyond capacity waits exactly as long as refill needs."""
        bucket = _TokenBucket(capacity=1, window_s=60.0, clock=lambda: 0.0)
        with patch('asyncio.sleep', new=AsyncMock()) as sleep:
            await bucket.acquire()
            await bucket.acquire()
        sleep.assert_awaited_once()
        (wait_s,), _ = sleep.await_args
        assert wait_s == pytest.approx(60.0)

    @pytest.mark.anyio
    async def test_refills_over_time(self) -> None:
        """Elapsed time between calls restores tokens before the next ask."""
        now = 0.0

        def _clock() -> float:
            return now

        bucket = _TokenBucket(capacity=1, window_s=60.0, clock=_clock)
        with patch('asyncio.sleep', new=AsyncMock()) as sleep:
            await bucket.acquire()
            now = 60.0
            await bucket.acquire()
        sleep.assert_not_awaited()


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
