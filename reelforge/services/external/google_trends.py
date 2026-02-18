from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("reelforge.external.google_trends")


class GoogleTrendsClient:
    """Placeholder for Google Trends API integration.
    TODO: Implement pytrends (unofficial Google Trends API) integration.
    """

    def __init__(self) -> None:
        logger.warning("GoogleTrendsClient initialized (placeholder implementation)")

    def get_trending_searches(self, region: str = "US") -> list[dict[str, Any]]:
        """Get currently trending search queries.

        Args:
            region: Region code (default: "US")

        Returns:
            List of trending search dicts

        TODO: Replace with actual pytrends implementation
        """
        logger.warning(f"GoogleTrendsClient.get_trending_searches called (placeholder) - region={region}")
        return [
            {"query": "mock trending topic 1", "traffic": "100k+", "related_queries": ["related 1", "related 2"]},
            {"query": "mock trending topic 2", "traffic": "50k+", "related_queries": ["related 3"]},
        ]

    def get_interest_over_time(self, keyword: str) -> dict[str, Any]:
        """Get interest over time for a specific keyword.

        Args:
            keyword: Search keyword to analyze

        Returns:
            Dict with timeline data and interest scores

        TODO: Replace with actual pytrends implementation
        """
        logger.warning(f"GoogleTrendsClient.get_interest_over_time called (placeholder) - keyword={keyword}")
        return {
            "keyword": keyword,
            "interest_score": 75,
            "trend_direction": "rising",
            "peak_date": "2025-02-10",
        }
