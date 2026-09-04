"""Tests for provider ordering, early exit, and 429 skip behaviour."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.generation.clients.stock import registry
from server.apps.generation.clients.stock.base import FootageCandidate
from server.apps.generation.clients.stock.registry import (
    build_providers,
    search_candidates,
)
from server.common.exceptions import RetryableProviderError


@pytest.fixture(autouse=True)
def _reset_cooldowns() -> None:
    """Isolate each test from cooldown state set by earlier tests."""
    registry._cooldown_until.clear()


def _candidate(
    provider: str,
    idx: int,
    width: int = 1920,
) -> FootageCandidate:
    return FootageCandidate(
        provider=provider,
        external_id=str(idx),
        media_type='video',
        download_url='https://e.test/v.mp4',
        thumb_url='https://e.test/t.jpg',
        source_page_url='https://e.test/p',
        width=width,
        height=1080,
        duration_s=10.0,
        license='pexels',
        license_url='',
        author='A',
        attribution_required=False,
        title='t',
        tags=(),
    )


def _provider(
    name: str,
    results: list[FootageCandidate],
) -> MagicMock:
    provider = MagicMock()
    provider.name = name
    provider.search = AsyncMock(return_value=results)
    return provider


def test_build_providers_preserves_order() -> None:
    """Provider priority order from config is preserved."""
    providers = build_providers(['wikimedia', 'pexels'])
    assert [provider.name for provider in providers] == [
        'wikimedia',
        'pexels',
    ]


def test_build_providers_ignores_unknown_names() -> None:
    """An unrecognised provider name is skipped, not fatal."""
    providers = build_providers(['pexels', 'not_a_provider'])
    assert [provider.name for provider in providers] == ['pexels']


@pytest.mark.anyio
async def test_early_exit_skips_lower_priority_providers() -> None:
    """Once the limit is met, later providers are never called."""
    first = _provider(
        'pexels',
        [_candidate('pexels', index) for index in range(8)],
    )
    second = _provider('pixabay', [_candidate('pixabay', 99)])

    with patch(
        'server.apps.generation.clients.stock.registry.cached_search',
        new=AsyncMock(
            side_effect=lambda provider, *args, **kwargs: (
                provider.search.return_value
            ),
        ),
    ) as search:
        results = await search_candidates(
            providers=[first, second],
            query='ocean',
            media_type='video',
            orientation='landscape',
            min_width=1280,
            min_duration_s=3.0,
            allowed_licenses=[],
            limit=8,
        )

    assert len(results) == 8
    assert {candidate.provider for candidate in results} == {'pexels'}
    search.assert_awaited_once()


@pytest.mark.anyio
async def test_falls_through_when_first_provider_is_thin() -> None:
    """A provider returning too few results falls through to the next."""
    first = _provider('pexels', [_candidate('pexels', 0)])
    second = _provider(
        'pixabay',
        [_candidate('pixabay', index) for index in range(5)],
    )

    with patch(
        'server.apps.generation.clients.stock.registry.cached_search',
        new=AsyncMock(
            side_effect=lambda provider, *args, **kwargs: (
                provider.search.return_value
            ),
        ),
    ):
        results = await search_candidates(
            providers=[first, second],
            query='ocean',
            media_type='video',
            orientation='landscape',
            min_width=1280,
            min_duration_s=3.0,
            allowed_licenses=[],
            limit=6,
        )

    assert len(results) == 6
    assert {candidate.provider for candidate in results} == {
        'pexels',
        'pixabay',
    }


@pytest.mark.anyio
async def test_quality_floor_filters_results() -> None:
    """Candidates below the width floor never reach the caller."""
    provider = _provider(
        'pexels',
        [
            _candidate('pexels', 0, width=640),
            _candidate('pexels', 1, width=1920),
        ],
    )

    with patch(
        'server.apps.generation.clients.stock.registry.cached_search',
        new=AsyncMock(
            side_effect=lambda current, *args, **kwargs: (
                current.search.return_value
            ),
        ),
    ):
        results = await search_candidates(
            providers=[provider],
            query='ocean',
            media_type='video',
            orientation='landscape',
            min_width=1280,
            min_duration_s=3.0,
            allowed_licenses=[],
            limit=8,
        )

    assert [candidate.external_id for candidate in results] == ['1']


@pytest.mark.anyio
async def test_rate_limited_provider_is_skipped_not_fatal() -> None:
    """A 429 from one provider must not fail the whole search."""
    first = _provider('pexels', [])
    second = _provider('pixabay', [_candidate('pixabay', 0)])

    async def _side_effect(
        provider: MagicMock,
        *args: object,
        **kwargs: object,
    ) -> object:
        if provider.name == 'pexels':
            raise RetryableProviderError(
                'rate',
                provider='pexels',
                status_code=429,
            )
        return provider.search.return_value

    with patch(
        'server.apps.generation.clients.stock.registry.cached_search',
        new=AsyncMock(side_effect=_side_effect),
    ):
        results = await search_candidates(
            providers=[first, second],
            query='ocean',
            media_type='video',
            orientation='landscape',
            min_width=1280,
            min_duration_s=3.0,
            allowed_licenses=[],
            limit=8,
        )

    assert [candidate.provider for candidate in results] == ['pixabay']


@pytest.mark.anyio
async def test_rate_limited_provider_starts_a_cooldown() -> None:
    """A 429 marks the provider as cooling down for subsequent calls."""
    provider = _provider('pexels', [])

    async def _side_effect(
        current: MagicMock,
        *args: object,
        **kwargs: object,
    ) -> object:
        raise RetryableProviderError(
            'rate',
            provider='pexels',
            status_code=429,
        )

    with patch(
        'server.apps.generation.clients.stock.registry.cached_search',
        new=AsyncMock(side_effect=_side_effect),
    ):
        await search_candidates(
            providers=[provider],
            query='ocean',
            media_type='video',
            orientation='landscape',
            min_width=1280,
            min_duration_s=3.0,
            allowed_licenses=[],
            limit=8,
        )

    assert registry._is_cooling_down('pexels') is True


@pytest.mark.anyio
async def test_cooling_down_provider_is_skipped_without_a_request() -> None:
    """A provider already cooling down is never called again this search."""
    registry._start_cooldown('pexels')
    first = _provider('pexels', [_candidate('pexels', 0)])
    second = _provider('pixabay', [_candidate('pixabay', 1)])

    with patch(
        'server.apps.generation.clients.stock.registry.cached_search',
        new=AsyncMock(
            side_effect=lambda provider, *args, **kwargs: (
                provider.search.return_value
            ),
        ),
    ) as search:
        results = await search_candidates(
            providers=[first, second],
            query='ocean',
            media_type='video',
            orientation='landscape',
            min_width=1280,
            min_duration_s=3.0,
            allowed_licenses=[],
            limit=8,
        )

    assert [candidate.provider for candidate in results] == ['pixabay']
    search.assert_awaited_once()
    called_provider = search.await_args.args[0]
    assert called_provider.name == 'pixabay'


@pytest.mark.anyio
async def test_non_rate_limit_error_propagates() -> None:
    """A 5xx is a real failure and must reach the stage's retry logic."""
    provider = _provider('pexels', [])

    async def _side_effect(
        current: MagicMock,
        *args: object,
        **kwargs: object,
    ) -> object:
        raise RetryableProviderError(
            'boom',
            provider='pexels',
            status_code=503,
        )

    with patch(
        'server.apps.generation.clients.stock.registry.cached_search',
        new=AsyncMock(side_effect=_side_effect),
    ):
        with pytest.raises(RetryableProviderError):
            await search_candidates(
                providers=[provider],
                query='ocean',
                media_type='video',
                orientation='landscape',
                min_width=1280,
                min_duration_s=3.0,
                allowed_licenses=[],
                limit=8,
            )
