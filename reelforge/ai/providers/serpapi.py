from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ***REMOVED***.ai.providers.community import SerpApiCommunityProvider
    from ***REMOVED***.ai.providers.trends import SerpApiTrendsProvider
    from ***REMOVED***.ai.providers.youtube import SerpApiYouTubeProvider
    from ***REMOVED***.services.serpapi.client import SerpApiClient

_singletons: dict[str, object] = {}


def _get_client() -> SerpApiClient:
    if "client" not in _singletons:
        from django.conf import settings

        from ***REMOVED***.services.serpapi.client import SerpApiClient
        _singletons["client"] = SerpApiClient(api_key=settings.SERPAPI_API_KEY)
    return _singletons["client"]  # type: ignore[return-value]


def get_youtube_search() -> SerpApiYouTubeProvider:
    if "youtube" not in _singletons:
        from ***REMOVED***.ai.providers.youtube import SerpApiYouTubeProvider
        _singletons["youtube"] = SerpApiYouTubeProvider(client=_get_client())
    return _singletons["youtube"]  # type: ignore[return-value]


def get_trends() -> SerpApiTrendsProvider:
    if "trends" not in _singletons:
        from ***REMOVED***.ai.providers.trends import SerpApiTrendsProvider
        _singletons["trends"] = SerpApiTrendsProvider(client=_get_client())
    return _singletons["trends"]  # type: ignore[return-value]


def get_community() -> SerpApiCommunityProvider:
    if "community" not in _singletons:
        from ***REMOVED***.ai.providers.community import SerpApiCommunityProvider
        _singletons["community"] = SerpApiCommunityProvider(client=_get_client())
    return _singletons["community"]  # type: ignore[return-value]
