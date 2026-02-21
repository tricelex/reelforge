from __future__ import annotations

import logging

from reelforge.agents.schemas import RisingTopic
from reelforge.agents.schemas import TrendData
from reelforge.agents.schemas import TrendPoint
from reelforge.services.exploding_topics.client import ExplodingTopicsClient
from reelforge.services.google_trends.client import GoogleTrendsClient

logger = logging.getLogger("reelforge.agents.providers.trends")


class GoogleTrendsProvider:
    """Provider that wraps GoogleTrendsClient and ExplodingTopicsClient.

    Satisfies TrendsProvider protocol.
    """

    def __init__(
        self,
        google_client: GoogleTrendsClient,
        exploding_client: ExplodingTopicsClient,
    ) -> None:
        self._google = google_client
        self._exploding = exploding_client

    def get_interest(self, keyword: str, timeframe: str = "today 30-d") -> TrendData:
        """Get search interest data for a keyword."""
        try:
            raw = self._google.get_interest(keyword=keyword, timeframe=timeframe)
            interest_over_time = [
                TrendPoint(date=point["date"], value=point["value"])
                for point in raw.get("interest_over_time", [])
            ]
            return TrendData(
                keyword=raw["keyword"],
                interest_score=raw["interest_score"],
                trend_direction=raw["trend_direction"],
                interest_over_time=interest_over_time,
                related_queries=raw.get("related_queries", []),
            )
        except Exception:
            logger.exception("GoogleTrendsProvider.get_interest failed for keyword='%s'", keyword)
            return TrendData(
                keyword=keyword,
                interest_score=0,
                trend_direction="STABLE",
                interest_over_time=[],
                related_queries=[],
            )

    def get_trending_searches(self, region: str = "US") -> list[str]:
        """Get currently trending search queries for a region."""
        try:
            return self._google.get_trending_searches(region=region)
        except Exception:
            logger.exception("GoogleTrendsProvider.get_trending_searches failed for region='%s'", region)
            return []

    def get_rising_topics(self, category: str = "") -> list[RisingTopic]:
        """Get rising topics — delegates to ExplodingTopicsClient."""
        try:
            raw_topics = self._exploding.get_rising(category=category)
            return [
                RisingTopic(
                    keyword=t.get("keyword", ""),
                    growth_rate=str(t.get("growth_rate", "")),
                    category=t.get("category", category),
                    description=t.get("description", ""),
                )
                for t in raw_topics
            ]
        except Exception:
            logger.exception("GoogleTrendsProvider.get_rising_topics failed for category='%s'", category)
            return []
