from __future__ import annotations

import logging
from typing import Any

from reelforge.services.reddit.exceptions import RedditAPIError
from reelforge.services.reddit.exceptions import RedditAuthError

logger = logging.getLogger("reelforge.reddit.client")

_DEFAULT_SUBREDDITS_BY_NICHE: dict[str, list[str]] = {
    "finance": ["personalfinance", "investing", "financialindependence"],
    "tech": ["technology", "programming", "artificial"],
    "health": ["fitness", "nutrition", "loseit"],
    "business": ["entrepreneur", "smallbusiness", "startups"],
    "education": ["learnprogramming", "todayilearned", "explainlikeimfive"],
}


class RedditClient:
    """Reddit client using PRAW (Python Reddit API Wrapper)."""

    def __init__(self, client_id: str = "", client_secret: str = "") -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self._reddit: Any = None

    def _get_reddit(self) -> Any:
        if self._reddit is None:
            import praw  # type: ignore[import-untyped]

            if not self.client_id or not self.client_secret:
                msg = "Reddit client_id and client_secret are required"
                raise RedditAuthError(msg)
            self._reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                user_agent="ReelForge Research Bot/1.0 (by /u/reelforge_bot)",
                read_only=True,
            )
        return self._reddit

    def _post_to_dict(self, post: Any) -> dict[str, Any]:
        return {
            "title": post.title,
            "score": post.score,
            "num_comments": post.num_comments,
            "url": post.url,
            "subreddit": str(post.subreddit),
            "created_utc": post.created_utc,
            "selftext": post.selftext[:500] if post.selftext else "",
        }

    def get_top_posts(
        self,
        niche: str,
        subreddits: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get top posts from subreddits relevant to a niche."""
        try:
            reddit = self._get_reddit()
            target_subreddits = subreddits or _DEFAULT_SUBREDDITS_BY_NICHE.get(niche.lower(), [niche])
            posts: list[dict[str, Any]] = []
            per_sub = max(5, limit // len(target_subreddits))

            for sub_name in target_subreddits:
                try:
                    subreddit = reddit.subreddit(sub_name)
                    for post in subreddit.top(time_filter="week", limit=per_sub):
                        posts.append(self._post_to_dict(post))
                except Exception as sub_exc:
                    logger.warning("Failed to fetch from r/%s: %s", sub_name, sub_exc)

            return sorted(posts, key=lambda p: p["score"], reverse=True)[:limit]
        except RedditAuthError:
            raise
        except Exception as exc:
            msg = f"Reddit get_top_posts failed for niche '{niche}': {exc}"
            raise RedditAPIError(msg) from exc

    def search_subreddit(
        self,
        subreddit_name: str,
        query: str,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Search for posts in a specific subreddit."""
        try:
            reddit = self._get_reddit()
            subreddit = reddit.subreddit(subreddit_name)
            posts = []
            for post in subreddit.search(query, limit=limit, sort="relevance", time_filter="year"):
                posts.append(self._post_to_dict(post))
            return posts
        except RedditAuthError:
            raise
        except Exception as exc:
            msg = f"Reddit search failed for r/{subreddit_name}: {exc}"
            raise RedditAPIError(msg) from exc

    def get_trending_posts(
        self,
        niche: str,
        time_filter: str = "week",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get trending posts across niche subreddits."""
        try:
            reddit = self._get_reddit()
            subreddit_names = _DEFAULT_SUBREDDITS_BY_NICHE.get(niche.lower(), [niche])
            combined = "+".join(subreddit_names)
            multi = reddit.subreddit(combined)
            posts = []
            for post in multi.hot(limit=limit):
                posts.append(self._post_to_dict(post))
            return posts
        except RedditAuthError:
            raise
        except Exception as exc:
            msg = f"Reddit trending posts failed for niche '{niche}': {exc}"
            raise RedditAPIError(msg) from exc
