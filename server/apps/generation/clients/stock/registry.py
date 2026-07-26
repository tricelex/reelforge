"""Provider registry and ordered multi-provider candidate search."""

from collections.abc import Callable, Sequence

import structlog
from django.conf import settings

from server.apps.generation.clients.stock.archive_org import ArchiveOrgProvider
from server.apps.generation.clients.stock.base import (
    FootageCandidate,
    FootageProvider,
    MediaType,
    passes_quality_floor,
)
from server.apps.generation.clients.stock.cache import cached_search
from server.apps.generation.clients.stock.openverse import OpenverseProvider
from server.apps.generation.clients.stock.pexels import PexelsProvider
from server.apps.generation.clients.stock.pixabay import PixabayProvider
from server.apps.generation.clients.stock.wikimedia import WikimediaProvider
from server.common.exceptions import RetryableProviderError

logger = structlog.get_logger(__name__)

_RATE_LIMIT_STATUS = 429


def build_providers(enabled: Sequence[str]) -> list[FootageProvider]:
    """Instantiate the named providers, preserving priority order."""
    factories: dict[str, Callable[[], FootageProvider]] = {
        'pexels': lambda: PexelsProvider(
            api_key=getattr(settings, 'PEXELS_API_KEY', ''),
        ),
        'pixabay': lambda: PixabayProvider(
            api_key=getattr(settings, 'PIXABAY_API_KEY', ''),
        ),
        'wikimedia': WikimediaProvider,
        'openverse': lambda: OpenverseProvider(
            client_id=getattr(settings, 'OPENVERSE_CLIENT_ID', ''),
            client_secret=getattr(
                settings,
                'OPENVERSE_CLIENT_SECRET',
                '',
            ),
            token=getattr(settings, 'OPENVERSE_API_TOKEN', ''),
        ),
        'archive_org': ArchiveOrgProvider,
    }
    providers: list[FootageProvider] = []
    for name in enabled:
        factory = factories.get(name)
        if factory is None:
            logger.warning('footage_provider_unknown', provider=name)
            continue
        providers.append(factory())
    return providers


async def search_candidates(
    *,
    providers: Sequence[FootageProvider],
    query: str,
    media_type: MediaType,
    orientation: str,
    min_width: int,
    min_duration_s: float,
    allowed_licenses: Sequence[str],
    limit: int,
) -> list[FootageCandidate]:
    """Search providers in priority order, stopping once ``limit`` is met.

    A provider that reports rate limiting (HTTP 429) is skipped for this
    call so a single exhausted quota cannot fail the scene. Other provider
    errors propagate to the stage's retry handling.
    """
    collected: list[FootageCandidate] = []
    for provider in providers:
        if len(collected) >= limit:
            break
        try:
            found = await cached_search(
                provider,
                query,
                media_type=media_type,
                orientation=orientation,
                min_width=min_width,
                limit=limit,
            )
        except RetryableProviderError as exc:
            if exc.status_code == _RATE_LIMIT_STATUS:
                logger.warning(
                    'footage_provider_rate_limited',
                    provider=provider.name,
                    query=query,
                )
                continue
            raise
        collected.extend(
            candidate
            for candidate in found
            if passes_quality_floor(
                candidate,
                min_width=min_width,
                min_duration_s=min_duration_s,
                allowed_licenses=allowed_licenses,
            )
        )
    return collected[:limit]
