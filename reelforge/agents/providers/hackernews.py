from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from reelforge.agents.schemas import CommunityPost

if TYPE_CHECKING:
    from reelforge.services.hackernews.client import HackerNewsClient

logger = logging.getLogger("reelforge.agents.providers.hackernews")


class HackerNewsProvider:
    """Provider that wraps HackerNewsClient and satisfies CommunitySearchProvider protocol."""

    def __init__(self, client: HackerNewsClient) -> None:
        self._client = client

    def search_discussions(
        self,
        niche: str,
        query: str | None = None,
        limit: int = 20,
    ) -> list[CommunityPost]:
        """Search HN for discussions about a niche. Combines Ask HN + stories, ranked by points."""
        search_term = query or niche
        try:
            ask_hits = self._client.search_ask_hn(search_term, limit=limit)
            story_hits = self._client.search_stories(search_term, limit=limit)

            seen: set[str] = set()
            combined: list[dict] = []
            for hit in ask_hits + story_hits:
                oid = hit["objectID"]
                if oid not in seen:
                    seen.add(oid)
                    combined.append(hit)

            combined.sort(key=lambda h: h["points"], reverse=True)

            return [
                CommunityPost(
                    title=h["title"],
                    score=h["points"],
                    num_comments=h["num_comments"],
                    url=h["url"],
                    source="hackernews",
                )
                for h in combined[:limit]
            ]
        except Exception:
            logger.exception(
                "HackerNewsProvider.search_discussions failed for niche='%s'",
                niche,
            )
            return []
