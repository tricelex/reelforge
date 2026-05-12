from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ***REMOVED***.ai.schemas.research import CommunityPost

if TYPE_CHECKING:
    from ***REMOVED***.services.serpapi.client import SerpApiClient

logger = logging.getLogger("***REMOVED***.ai.providers.community")


class SerpApiCommunityProvider:
    """CommunitySearchProvider backed by SerpAPI Google Search engine.

    Searches across Reddit, HackerNews, Quora, and other community sites
    using Google's site-operator to surface relevant discussions.
    """

    def __init__(self, client: SerpApiClient) -> None:
        self._client = client

    def search_discussions(
        self,
        niche: str,
        query: str | None = None,
        limit: int = 20,
    ) -> list[CommunityPost]:
        """Search for community discussions about a niche using Google Search.

        Searches for forum/community discussions (Reddit, HN, Quora, etc.)
        and returns results as CommunityPost objects sorted by position.
        """
        search_term = f"{query or niche} forum community discussion questions"
        try:
            result = self._client.search_google(query=search_term, num=limit)
            organic: list[dict] = result.get("organic_results", [])
            return [
                CommunityPost(
                    title=item.get("title", ""),
                    score=item.get("position", 0),
                    num_comments=0,
                    url=item.get("link", ""),
                    source="google",
                )
                for item in organic[:limit]
                if item.get("title")
            ]
        except Exception:
            logger.exception("SerpApiCommunityProvider.search_discussions failed for niche='%s'", niche)
            return []
