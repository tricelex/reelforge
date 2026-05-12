from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reelforge.ai.providers.web_search import TavilyProvider

_singletons: dict[str, object] = {}


def get_web_search() -> TavilyProvider:
    if "web_search" not in _singletons:
        from django.conf import settings

        from reelforge.ai.providers.web_search import TavilyProvider
        from reelforge.services.tavily.client import TavilyResearchClient
        _singletons["web_search"] = TavilyProvider(client=TavilyResearchClient(api_key=settings.TAVILY_API_KEY))
    return _singletons["web_search"]  # type: ignore[return-value]
