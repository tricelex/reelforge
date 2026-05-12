from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ***REMOVED***.ai.schemas.research import RisingTopic
from ***REMOVED***.ai.schemas.research import TrendData
from ***REMOVED***.ai.schemas.research import TrendPoint

if TYPE_CHECKING:
    from ***REMOVED***.services.serpapi.client import SerpApiClient

logger = logging.getLogger("***REMOVED***.ai.providers.trends")


class SerpApiTrendsProvider:
    """TrendsProvider backed by SerpAPI Google Trends engine."""

    def __init__(self, client: SerpApiClient) -> None:
        self._client = client

    def get_interest(self, keyword: str, timeframe: str = "today 30-d") -> TrendData:
        """Get search interest data for a keyword."""
        try:
            ts_data = self._client.get_trends_timeseries([keyword], timeframe=timeframe)
            timeline = ts_data.get("timeline_data", [])

            # Compute interest_score as average of extracted values over timeline
            all_values: list[int] = []
            interest_over_time: list[TrendPoint] = []
            for point in timeline:
                date_str = point.get("date", "")
                for val_entry in point.get("values", []):
                    if val_entry.get("query", "") == keyword or len(point.get("values", [])) == 1:
                        extracted = val_entry.get("extracted_value", val_entry.get("value", 0))
                        try:
                            int_val = int(extracted)
                        except (TypeError, ValueError):
                            int_val = 0
                        all_values.append(int_val)
                        interest_over_time.append(TrendPoint(date=date_str, value=int_val))
                        break

            interest_score = int(sum(all_values) / len(all_values)) if all_values else 0

            # Compute trend direction: compare first half vs second half averages
            mid = len(all_values) // 2
            if mid > 0:
                first_half_avg = sum(all_values[:mid]) / mid
                second_half_avg = sum(all_values[mid:]) / len(all_values[mid:])
                if second_half_avg > first_half_avg * 1.1:
                    trend_direction = "RISING"
                elif second_half_avg < first_half_avg * 0.9:
                    trend_direction = "DECLINING"
                else:
                    trend_direction = "STABLE"
            else:
                trend_direction = "STABLE"

            # Fetch related queries for extra context
            related_data = self._client.get_trends_related_queries(keyword)
            related_queries = [q.get("query", "") for q in related_data.get("top", [])[:10]]

            return TrendData(
                keyword=keyword,
                interest_score=interest_score,
                trend_direction=trend_direction,
                interest_over_time=interest_over_time,
                related_queries=related_queries,
            )

        except Exception as exc:
            exc_str = str(exc)
            if "429" in exc_str or "rate limit" in exc_str.lower():
                logger.warning(
                    "SerpApiTrendsProvider.get_interest rate-limited for keyword='%s'",
                    keyword,
                )
            else:
                logger.exception("SerpApiTrendsProvider.get_interest failed for keyword='%s'", keyword)
            return TrendData(
                keyword=keyword,
                interest_score=0,
                trend_direction="STABLE",
                interest_over_time=[],
                related_queries=[],
            )

    def get_interest_batch(self, keywords: list[str], timeframe: str = "today 3-m") -> list[TrendData]:
        """Fetch trend data for multiple keywords using SerpAPI's multi-keyword timeseries.

        SerpAPI allows up to 5 keywords per call. Batches are chunked accordingly.
        """
        results: list[TrendData] = []
        chunks = [keywords[i : i + 5] for i in range(0, len(keywords), 5)]

        for chunk in chunks:
            try:
                ts_data = self._client.get_trends_timeseries(chunk, timeframe=timeframe)
                timeline = ts_data.get("timeline_data", [])
                averages = ts_data.get("averages", [])

                # Build per-keyword value lists from timeline
                kw_values: dict[str, list[int]] = {kw: [] for kw in chunk}
                kw_timeline: dict[str, list[TrendPoint]] = {kw: [] for kw in chunk}

                for point in timeline:
                    date_str = point.get("date", "")
                    for val_entry in point.get("values", []):
                        q = val_entry.get("query", "")
                        if q in kw_values:
                            extracted = val_entry.get("extracted_value", val_entry.get("value", 0))
                            try:
                                int_val = int(extracted)
                            except (TypeError, ValueError):
                                int_val = 0
                            kw_values[q].append(int_val)
                            kw_timeline[q].append(TrendPoint(date=date_str, value=int_val))

                # Build per-keyword averages map from the averages list
                avg_map: dict[str, int] = {}
                for avg_entry in averages:
                    q = avg_entry.get("query", "")
                    val = avg_entry.get("value", 0)
                    try:
                        avg_map[q] = int(val)
                    except (TypeError, ValueError):
                        avg_map[q] = 0

                for kw in chunk:
                    vals = kw_values.get(kw, [])
                    interest_score = avg_map.get(kw, int(sum(vals) / len(vals)) if vals else 0)

                    mid = len(vals) // 2
                    if mid > 0:
                        first_avg = sum(vals[:mid]) / mid
                        second_avg = sum(vals[mid:]) / len(vals[mid:])
                        if second_avg > first_avg * 1.1:
                            trend_direction = "RISING"
                        elif second_avg < first_avg * 0.9:
                            trend_direction = "DECLINING"
                        else:
                            trend_direction = "STABLE"
                    else:
                        trend_direction = "STABLE"

                    results.append(
                        TrendData(
                            keyword=kw,
                            interest_score=interest_score,
                            trend_direction=trend_direction,
                            interest_over_time=kw_timeline.get(kw, []),
                            related_queries=[],
                        )
                    )

            except Exception as exc:
                exc_str = str(exc)
                if "429" in exc_str or "rate limit" in exc_str.lower():
                    logger.warning(
                        "SerpApiTrendsProvider.get_interest_batch rate-limited for chunk=%s",
                        chunk,
                    )
                else:
                    logger.exception("SerpApiTrendsProvider.get_interest_batch failed for chunk=%s", chunk)
                results.extend(
                    TrendData(
                        keyword=kw,
                        interest_score=0,
                        trend_direction="STABLE",
                        interest_over_time=[],
                        related_queries=[],
                    )
                    for kw in chunk
                )

        return results

    def get_trending_searches(self, region: str = "US") -> list[str]:
        """Get currently trending search queries for a region."""
        try:
            data = self._client.get_trends_related_queries("trending topics", geo=region)
            return [q.get("query", "") for q in data.get("top", [])[:20] if q.get("query")]
        except Exception:
            logger.exception("SerpApiTrendsProvider.get_trending_searches failed for region='%s'", region)
            return []

    def get_rising_topics(self, category: str = "") -> list[RisingTopic]:
        """Get rising topics via Google Trends related topics."""
        try:
            keyword = category or "trending topics"
            data = self._client.get_trends_related_topics(keyword, geo="US")
            return [
                RisingTopic(
                    keyword=item.get("topic", ""),
                    growth_rate=str(item.get("value", "")),
                    category=category,
                    description="",
                )
                for item in data.get("rising", [])
                if item.get("topic")
            ]
        except Exception:
            logger.exception("SerpApiTrendsProvider.get_rising_topics failed for category='%s'", category)
            return []
