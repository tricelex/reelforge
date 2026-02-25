from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any

from ***REMOVED***.services.rising_topics.exceptions import RisingTopicsError

if TYPE_CHECKING:
    from ***REMOVED***.services.google_trends.client import GoogleTrendsClient
    from ***REMOVED***.services.hackernews.client import HackerNewsClient

logger = logging.getLogger("***REMOVED***.rising_topics.client")


class RisingTopicsClient:
    """Rising-topics discovery using free signals: pytrends related_queries and HackerNews recent stories.

    Replaces the ExplodingTopicsClient stub with real data from two sources:
    - pytrends ``related_queries()`` rising: breakout/high-% search queries over last 3 months.
    - HackerNews recent stories: posts gaining momentum on news.ycombinator.com.

    Both signals are combined and returned in the same shape as ExplodingTopicsClient.get_rising().
    """

    def __init__(
        self,
        google_client: GoogleTrendsClient,
        hackernews_client: HackerNewsClient,
    ) -> None:
        self._google = google_client
        self._hackernews = hackernews_client

    def get_rising(self, category: str = "") -> list[dict[str, Any]]:
        """Return rising topics for a category.

        Args:
            category: Niche category (e.g. "technology", "finance", "health"). Empty = general.

        Returns:
            List of dicts with keys: keyword, growth_rate, category, description.

        Raises:
            RisingTopicsError: If all signals fail and no results are available.
        """
        results: list[dict[str, Any]] = []

        # Signal 1 — pytrends related_queries rising (run first; shares pytrends instance)
        try:
            pytrends_results = self._get_pytrends_rising(category)
            results.extend(pytrends_results)
            logger.info(
                "pytrends rising queries returned %d results for category='%s'",
                len(pytrends_results),
                category,
            )
        except Exception as exc:
            logger.warning(
                "pytrends rising queries failed for category='%s': %s",
                category,
                exc,
            )

        # Signal 2 — HackerNews recent stories
        try:
            hn_results = self._get_hackernews_rising(category)
            results.extend(hn_results)
            logger.info(
                "HackerNews recent stories returned %d results for category='%s'",
                len(hn_results),
                category,
            )
        except Exception as exc:
            logger.warning(
                "HackerNews recent stories failed for category='%s': %s",
                category,
                exc,
            )

        if not results:
            msg = f"All rising topics signals failed for category='{category}'"
            raise RisingTopicsError(msg)

        return results

    def _get_pytrends_rising(self, category: str) -> list[dict[str, Any]]:
        """Fetch rising related queries from pytrends for the given category keyword."""
        keyword = category or "trending"
        pytrends = self._google._get_pytrends()
        pytrends.build_payload([keyword], timeframe="today 3-m", geo="US")
        related = pytrends.related_queries()

        category_data: dict[str, Any] = related.get(keyword, {}) or {}
        rising_df = category_data.get("rising")

        if rising_df is None or rising_df.empty:
            return []

        results: list[dict[str, Any]] = []
        for _, row in rising_df.head(10).iterrows():
            value = row.get("value", 0)
            # pytrends value is either an integer (%) or the string "Breakout"
            growth_rate = "Breakout" if str(value).lower() == "breakout" else f"{value}%"
            results.append(
                {
                    "keyword": str(row["query"]),
                    "growth_rate": growth_rate,
                    "category": category or "general",
                    "description": f"Rising search query related to {keyword}",
                }
            )
        return results

    def _get_hackernews_rising(self, category: str) -> list[dict[str, Any]]:
        """Fetch recent HackerNews stories to identify rising topics in the category."""
        query = category or "technology"
        try:
            stories = self._hackernews.get_recent_stories(query, limit=10)
        except Exception as exc:
            logger.warning("HackerNews get_recent_stories failed for query='%s': %s", query, exc)
            return []

        results: list[dict[str, Any]] = []
        for story in stories:
            title = story.get("title", "")
            if not title:
                continue
            points = story.get("points") or 0
            growth_rate = f"{points} points" if points else "rising"
            results.append(
                {
                    "keyword": title[:120],
                    "growth_rate": growth_rate,
                    "category": category or "general",
                    "description": f"Trending on HackerNews ({story.get('num_comments', 0)} comments)",
                }
            )
        return results
