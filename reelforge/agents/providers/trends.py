from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from reelforge.agents.schemas import RisingTopic
from reelforge.agents.schemas import TrendData
from reelforge.agents.schemas import TrendPoint

if TYPE_CHECKING:
    from reelforge.services.google_trends.client import GoogleTrendsClient
    from reelforge.services.rising_topics.client import RisingTopicsClient

logger = logging.getLogger("reelforge.agents.providers.trends")


class GoogleTrendsProvider:
    """Provider that wraps GoogleTrendsClient and RisingTopicsClient.

    Satisfies TrendsProvider protocol.
    """

    def __init__(
        self,
        google_client: GoogleTrendsClient,
        rising_client: RisingTopicsClient,
    ) -> None:
        self._google = google_client
        self._rising = rising_client

    def get_interest(self, keyword: str, timeframe: str = "today 30-d") -> TrendData:
        """Get search interest data for a keyword."""
        try:
            raw = self._google.get_interest(keyword=keyword, timeframe=timeframe)
            interest_over_time = [
                TrendPoint(date=point["date"], value=point["value"]) for point in raw.get("interest_over_time", [])
            ]
            return TrendData(
                keyword=raw["keyword"],
                interest_score=raw["interest_score"],
                trend_direction=raw["trend_direction"],
                interest_over_time=interest_over_time,
                related_queries=raw.get("related_queries", []),
            )
        except Exception as exc:
            exc_str = str(exc)
            if "429" in exc_str or "TooManyRequests" in exc_str:
                logger.warning(
                    "GoogleTrendsProvider.get_interest rate-limited (429) for keyword='%s' — returning empty TrendData",
                    keyword,
                )
            else:
                logger.exception("GoogleTrendsProvider.get_interest failed for keyword='%s'", keyword)
            return TrendData(
                keyword=keyword,
                interest_score=0,
                trend_direction="STABLE",
                interest_over_time=[],
                related_queries=[],
            )

    def get_interest_batch(self, keywords: list[str], timeframe: str = "today 3-m") -> list[TrendData]:
        """Fetch trend data for multiple keywords in a single batch call."""
        results = []
        for i, kw in enumerate(keywords):
            if i > 0:
                time.sleep(2)
            results.append(self.get_interest(keyword=kw, timeframe=timeframe))
        return results

    def get_trending_searches(self, region: str = "US") -> list[str]:
        """Get currently trending search queries for a region."""
        try:
            return self._google.get_trending_searches(region=region)
        except Exception as exc:
            exc_str = str(exc)
            if "429" in exc_str or "TooManyRequests" in exc_str:
                logger.warning(
                    "GoogleTrendsProvider.get_trending_searches rate-limited (429) for region='%s' — returning empty list",
                    region,
                )
            else:
                logger.exception("GoogleTrendsProvider.get_trending_searches failed for region='%s'", region)
            return []

    def get_rising_topics(self, category: str = "") -> list[RisingTopic]:
        """Get rising topics — delegates to RisingTopicsClient."""
        try:
            raw_topics = self._rising.get_rising(category=category)
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
