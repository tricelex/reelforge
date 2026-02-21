from __future__ import annotations

import logging

from reelforge.agents.schemas import RedditPost
from reelforge.services.reddit.client import RedditClient

logger = logging.getLogger("reelforge.agents.providers.reddit")


class RedditProvider:
    """Provider that wraps RedditClient and satisfies RedditProvider protocol."""

    def __init__(self, client: RedditClient) -> None:
        self._client = client

    def get_top_posts(
        self,
        niche: str,
        subreddits: list[str] | None = None,
        limit: int = 20,
    ) -> list[RedditPost]:
        """Get top Reddit posts for a niche."""
        try:
            raw_posts = self._client.get_top_posts(
                niche=niche,
                subreddits=subreddits,
                limit=limit,
            )
            return [
                RedditPost(
                    title=p.get("title", ""),
                    score=p.get("score", 0),
                    num_comments=p.get("num_comments", 0),
                    url=p.get("url", ""),
                    subreddit=p.get("subreddit", ""),
                )
                for p in raw_posts
            ]
        except Exception:
            logger.exception("RedditProvider.get_top_posts failed for niche='%s'", niche)
            return []
