from __future__ import annotations

import logging
from typing import Any

from reelforge.services.google_trends.exceptions import GoogleTrendsAPIError

logger = logging.getLogger("reelforge.google_trends.client")


class GoogleTrendsClient:
    """Google Trends client using the pytrends library (unofficial API)."""

    def __init__(self) -> None:
        self._pytrends: Any = None

    def _get_pytrends(self) -> Any:
        if self._pytrends is None:
            from pytrends.request import TrendReq  # type: ignore[import-untyped]

            self._pytrends = TrendReq(hl="en-US", tz=360, timeout=(10, 25))
        return self._pytrends

    def get_interest(self, keyword: str, timeframe: str = "today 30-d") -> dict[str, Any]:
        """Get search interest data for a keyword over time."""
        try:
            pytrends = self._get_pytrends()
            pytrends.build_payload([keyword], timeframe=timeframe, geo="US")
            df = pytrends.interest_over_time()

            if df.empty or keyword not in df.columns:
                return {
                    "keyword": keyword,
                    "interest_score": 0,
                    "trend_direction": "STABLE",
                    "interest_over_time": [],
                    "related_queries": [],
                }

            interest_vals: list[int] = [int(v) for v in df[keyword].tolist()]
            interest_score = int(df[keyword].mean())

            if len(interest_vals) >= 4:
                mid = len(interest_vals) // 2
                first_avg = sum(interest_vals[:mid]) / mid
                second_avg = sum(interest_vals[mid:]) / len(interest_vals[mid:])
                if second_avg > first_avg * 1.1:
                    trend_direction = "RISING"
                elif second_avg < first_avg * 0.9:
                    trend_direction = "DECLINING"
                else:
                    trend_direction = "STABLE"
            else:
                trend_direction = "STABLE"

            related_queries: list[str] = []
            try:
                related = pytrends.related_queries()
                if keyword in related and related[keyword] and "top" in related[keyword]:
                    top_df = related[keyword]["top"]
                    if top_df is not None and not top_df.empty:
                        related_queries = top_df["query"].head(10).tolist()
            except Exception:
                pass

            dates = [str(d.date()) for d in df.index.tolist()]
            interest_over_time = [{"date": d, "value": v} for d, v in zip(dates, interest_vals, strict=False)]

            return {
                "keyword": keyword,
                "interest_score": interest_score,
                "trend_direction": trend_direction,
                "interest_over_time": interest_over_time,
                "related_queries": related_queries,
            }
        except GoogleTrendsAPIError:
            raise
        except Exception as exc:
            msg = f"Google Trends request failed for '{keyword}': {exc}"
            raise GoogleTrendsAPIError(msg) from exc

    def get_trending_searches(self, region: str = "US") -> list[str]:
        """Get currently trending search queries for a region."""
        try:
            pytrends = self._get_pytrends()
            trending = pytrends.trending_searches(pn=region.lower())
            return trending[0].tolist() if not trending.empty else []
        except GoogleTrendsAPIError:
            raise
        except Exception as exc:
            msg = f"Trending searches failed for region '{region}': {exc}"
            raise GoogleTrendsAPIError(msg) from exc

    def get_rising_topics(self, category: str = "") -> list[dict[str, Any]]:
        """Get real-time trending topics."""
        try:
            pytrends = self._get_pytrends()
            realtime_df = pytrends.realtime_trending_searches(pn="US")
            topics = []
            for _, row in realtime_df.head(20).iterrows():
                topics.append(
                    {
                        "keyword": str(row.get("title", "")),
                        "growth_rate": "rising",
                        "category": category or "general",
                        "description": str(row.get("entityNames", "")),
                    }
                )
            return topics
        except GoogleTrendsAPIError:
            raise
        except Exception as exc:
            msg = f"Rising topics failed: {exc}"
            raise GoogleTrendsAPIError(msg) from exc
