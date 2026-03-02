from __future__ import annotations

import logging
import re
from typing import Any

import serpapi

from reelforge.services.serpapi.exceptions import SerpApiAuthError
from reelforge.services.serpapi.exceptions import SerpApiError
from reelforge.services.serpapi.exceptions import SerpApiRateLimitError

logger = logging.getLogger("reelforge.providers.serpapi")


def _classify_error(exc: Exception) -> SerpApiError:
    """Map a raw exception to a typed SerpApiError subclass."""
    msg = str(exc).lower()
    if "429" in msg or "rate limit" in msg or "too many requests" in msg:
        return SerpApiRateLimitError(str(exc))
    if "401" in msg or "403" in msg or "invalid api" in msg or "unauthorized" in msg:
        return SerpApiAuthError(str(exc))
    return SerpApiError(str(exc))


class SerpApiClient:
    """Thin wrapper around the official `serpapi` library.

    Provides typed methods for three SerpAPI engines:
      - YouTube Search
      - Google Trends
      - Google Search (organic + news)

    All public methods raise SerpApiError (or subclasses) on failure.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = serpapi.Client(api_key=api_key)

    # ── YouTube Engine ────────────────────────────────────────────────────────

    def search_videos(
        self,
        query: str,
        max_results: int = 20,
        gl: str = "us",
        hl: str = "en",
    ) -> list[dict[str, Any]]:
        """Search YouTube videos. Returns normalized result dicts."""
        try:
            results = self._client.search(
                {
                    "engine": "youtube",
                    "search_query": query,
                    "gl": gl,
                    "hl": hl,
                }
            )
        except Exception as exc:
            raise _classify_error(exc) from exc

        raw_videos: list[dict[str, Any]] = results.get("video_results", [])
        normalized: list[dict[str, Any]] = []
        for item in raw_videos[:max_results]:
            channel_info = item.get("channel") or {}
            channel_link = channel_info.get("link", "")
            normalized.append(
                {
                    "title": item.get("title", ""),
                    "video_id": item.get("id", ""),
                    "url": item.get("link", ""),
                    "channel_name": channel_info.get("name", ""),
                    "channel_id": channel_info.get("id", ""),
                    "channel_handle": _extract_channel_handle(channel_link),
                    "channel_url": channel_link,
                    "views": item.get("views"),
                    "duration_seconds": _parse_duration_str(item.get("length", "")),
                    "published_date": item.get("published_date"),
                    "thumbnail": (item.get("thumbnail") or {}).get("static", ""),
                    "description": item.get("description", ""),
                }
            )
        return normalized

    def search_channels(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Search YouTube channels. Returns normalized result dicts."""
        try:
            results = self._client.search(
                {
                    "engine": "youtube",
                    "search_query": query,
                }
            )
        except Exception as exc:
            raise _classify_error(exc) from exc

        raw_channels: list[dict[str, Any]] = results.get("channel_results", [])
        normalized: list[dict[str, Any]] = []
        for item in raw_channels[:max_results]:
            subs_raw = item.get("subscribers")
            subscribers_count = (
                int(subs_raw) if isinstance(subs_raw, (int, float)) else _parse_subscriber_count(str(subs_raw or ""))
            )
            channel_link = item.get("link", "")
            handle = item.get("handle", "") or _extract_channel_handle(channel_link)
            thumb_raw = item.get("thumbnail") or ""
            thumbnail = (
                thumb_raw
                if isinstance(thumb_raw, str)
                else (thumb_raw.get("static", "") if isinstance(thumb_raw, dict) else "")
            )
            normalized.append(
                {
                    "channel_name": item.get("title", ""),
                    "channel_id": item.get("id", ""),
                    "channel_handle": handle,
                    "channel_url": channel_link,
                    "subscribers_count": subscribers_count,
                    "video_count": item.get("video_count"),
                    "description": item.get("description", ""),
                    "thumbnail": thumbnail,
                }
            )
        return normalized

    def search_channel_with_videos(
        self,
        query: str,
        max_videos: int = 10,
        gl: str = "us",
        hl: str = "en",
    ) -> dict[str, Any]:
        """Search YouTube for a channel and return metadata + recent video titles in one call.

        Returns:
            {
                "channel_name": str,
                "channel_handle": str,   # e.g. "@simonscrapes"
                "channel_url": str,
                "subscriber_count": int,
                "description": str,
                "thumbnail": str,
                "recent_video_titles": list[str],
                "found": bool,           # False if channel_results was empty
            }
        """
        try:
            results = self._client.search({"engine": "youtube", "search_query": query, "gl": gl, "hl": hl})
        except Exception as exc:
            raise _classify_error(exc) from exc

        channel_results: list[dict[str, Any]] = results.get("channel_results", [])
        ch = channel_results[0] if channel_results else {}

        subs_raw = ch.get("subscribers")
        subscriber_count = (
            int(subs_raw) if isinstance(subs_raw, (int, float)) else _parse_subscriber_count(str(subs_raw or ""))
        )
        channel_link = ch.get("link", "")
        handle = ch.get("handle", "") or _extract_channel_handle(channel_link)
        thumb_raw = ch.get("thumbnail") or ""
        thumbnail = (
            thumb_raw
            if isinstance(thumb_raw, str)
            else (thumb_raw.get("static", "") if isinstance(thumb_raw, dict) else "")
        )

        latest_key = next((k for k in results if k.startswith("latest_from_")), None)
        video_list: list[dict[str, Any]] = (
            results.get(latest_key, []) if latest_key else results.get("video_results", [])
        )
        recent_titles = [v.get("title", "") for v in video_list[:max_videos] if v.get("title")]

        return {
            "channel_name": ch.get("title", ""),
            "channel_handle": handle,
            "channel_url": channel_link,
            "subscriber_count": subscriber_count,
            "description": ch.get("description", ""),
            "thumbnail": thumbnail,
            "recent_video_titles": recent_titles,
            "found": bool(channel_results),
        }

    def search_shorts(
        self,
        query: str,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """Search YouTube Shorts. Returns normalized result dicts."""
        try:
            results = self._client.search(
                {
                    "engine": "youtube",
                    "search_query": query,
                }
            )
        except Exception as exc:
            raise _classify_error(exc) from exc

        raw_shorts: list[dict[str, Any]] = results.get("shorts_results", [])
        normalized: list[dict[str, Any]] = []
        for item in raw_shorts[:max_results]:
            normalized.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "channel_name": (item.get("channel") or {}).get("name", ""),
                    "views": item.get("views"),
                    "thumbnail": (item.get("thumbnail") or {}).get("static", ""),
                }
            )
        return normalized

    # ── Google Trends Engine ──────────────────────────────────────────────────

    def get_trends_timeseries(
        self,
        keywords: list[str],
        timeframe: str = "today 3-m",
        geo: str = "US",
    ) -> dict[str, Any]:
        """Fetch Google Trends timeseries for up to 5 keywords.

        Returns:
            {
                "timeline_data": [{"date": str, "values": [{"query": str, "value": int}]}],
                "averages": [{"query": str, "value": int}],
            }
        """
        try:
            results = self._client.search(
                {
                    "engine": "google_trends",
                    "q": ",".join(keywords[:5]),
                    "date": timeframe,
                    "geo": geo,
                    "data_type": "TIMESERIES",
                }
            )
        except Exception as exc:
            raise _classify_error(exc) from exc

        interest_data: list[dict[str, Any]] = results.get("interest_over_time", {}).get("timeline_data", [])
        averages: list[dict[str, Any]] = results.get("interest_over_time", {}).get("averages", [])

        return {
            "timeline_data": interest_data,
            "averages": averages,
        }

    def get_trends_related_queries(
        self,
        keyword: str,
        geo: str = "US",
    ) -> dict[str, Any]:
        """Fetch Google Trends related queries for a keyword.

        Returns:
            {
                "rising": [{"query": str, "value": str}],
                "top": [{"query": str, "value": str}],
            }
        """
        try:
            results = self._client.search(
                {
                    "engine": "google_trends",
                    "q": keyword,
                    "geo": geo,
                    "data_type": "RELATED_QUERIES",
                }
            )
        except Exception as exc:
            raise _classify_error(exc) from exc

        related: dict[str, Any] = results.get("related_queries", {})
        return {
            "rising": related.get("rising", []),
            "top": related.get("top", []),
        }

    def get_trends_related_topics(
        self,
        keyword: str,
        geo: str = "US",
    ) -> dict[str, Any]:
        """Fetch Google Trends related topics for a keyword.

        Returns:
            {
                "rising": [{"topic": str, "value": str}],
                "top": [{"topic": str, "value": str}],
            }
        """
        try:
            results = self._client.search(
                {
                    "engine": "google_trends",
                    "q": keyword,
                    "geo": geo,
                    "data_type": "RELATED_TOPICS",
                }
            )
        except Exception as exc:
            raise _classify_error(exc) from exc

        related: dict[str, Any] = results.get("related_topics", {})

        def _extract_topic(item: dict[str, Any]) -> dict[str, Any]:
            topic_info = item.get("topic", {}) or {}
            return {
                "topic": topic_info.get("title", item.get("query", "")),
                "value": item.get("value", ""),
            }

        return {
            "rising": [_extract_topic(i) for i in related.get("rising", [])],
            "top": [_extract_topic(i) for i in related.get("top", [])],
        }

    # ── Google Search Engine ──────────────────────────────────────────────────

    def search_google(
        self,
        query: str,
        num: int = 10,
        gl: str = "us",
        hl: str = "en",
        tbm: str | None = None,
    ) -> dict[str, Any]:
        """Run a Google search and return the full result dict.

        Returns keys such as: organic_results, answer_box, related_searches, ...
        """
        params: dict[str, Any] = {
            "engine": "google",
            "q": query,
            "num": num,
            "gl": gl,
            "hl": hl,
        }
        if tbm:
            params["tbm"] = tbm
        try:
            results = self._client.search(params)
        except Exception as exc:
            raise _classify_error(exc) from exc

        return dict(results)

    def search_news(
        self,
        query: str,
        num: int = 10,
        gl: str = "us",
    ) -> list[dict[str, Any]]:
        """Search Google News for a query. Returns list of article dicts."""
        try:
            results = self._client.search(
                {
                    "engine": "google",
                    "q": query,
                    "tbm": "nws",
                    "num": num,
                    "gl": gl,
                }
            )
        except Exception as exc:
            raise _classify_error(exc) from exc

        raw_news: list[dict[str, Any]] = results.get("news_results", [])
        return [
            {
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "date": item.get("date", ""),
                "source": item.get("source", ""),
            }
            for item in raw_news[:num]
        ]


# ── Private helpers ───────────────────────────────────────────────────────────


def _parse_duration_str(duration_str: str) -> int | None:
    """Parse a duration string like "10:23" or "1:02:45" to total seconds."""
    if not duration_str:
        return None
    parts = duration_str.strip().split(":")
    try:
        int_parts = [int(p) for p in parts]
    except ValueError:
        return None
    if len(int_parts) == 2:  # mm:ss  # noqa: PLR2004
        return int_parts[0] * 60 + int_parts[1]
    if len(int_parts) == 3:  # hh:mm:ss  # noqa: PLR2004
        return int_parts[0] * 3600 + int_parts[1] * 60 + int_parts[2]
    return None


def _extract_channel_handle(url: str) -> str:
    """Extract '@Handle' from 'https://www.youtube.com/@Handle'."""
    if not url:
        return ""
    match = re.search(r"youtube\.com/@([\w.-]+)", url)
    return f"@{match.group(1)}" if match else ""


def _parse_subscriber_count(text: str) -> int:
    """Parse a subscriber count string like '1.2M subscribers' into an integer."""
    if not text:
        return 0
    text = text.lower().replace(",", "").replace(" subscribers", "").replace(" subscriber", "").strip()
    match = re.search(r"([\d.]+)\s*([kmb]?)", text)
    if not match:
        return 0
    number_str, suffix = match.group(1), match.group(2)
    try:
        number = float(number_str)
    except ValueError:
        return 0
    multipliers = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
    return int(number * multipliers.get(suffix, 1))
