from __future__ import annotations

import logging
from typing import Any

from reelforge.agents.schemas import VideoResult
from reelforge.services.youtube.client import YouTubeClient

logger = logging.getLogger("reelforge.agents.providers.youtube")

_ISO8601_DURATION_SUFFIXES = {"H": 3600, "M": 60, "S": 1}


def _parse_duration(iso_duration: str) -> int | None:
    """Parse ISO 8601 duration string (e.g. PT1H2M3S) to seconds."""
    if not iso_duration or not iso_duration.startswith("PT"):
        return None
    total = 0
    current = ""
    for ch in iso_duration[2:]:
        if ch.isdigit():
            current += ch
        elif ch in _ISO8601_DURATION_SUFFIXES and current:
            total += int(current) * _ISO8601_DURATION_SUFFIXES[ch]
            current = ""
    return total


def _item_to_video_result(item: dict[str, Any]) -> VideoResult:
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    details = item.get("contentDetails", {})
    video_id = item.get("id", "")
    if isinstance(video_id, dict):
        video_id = video_id.get("videoId", "")

    return VideoResult(
        title=snippet.get("title", ""),
        url=f"https://youtube.com/watch?v={video_id}",
        channel=snippet.get("channelTitle", ""),
        channel_id=snippet.get("channelId", ""),
        views=int(stats["viewCount"]) if "viewCount" in stats else None,
        likes=int(stats["likeCount"]) if "likeCount" in stats else None,
        published_at=snippet.get("publishedAt"),
        duration_seconds=_parse_duration(details.get("duration", "")) if details else None,
    )


class YouTubeProvider:
    """Provider that wraps YouTubeClient and satisfies VideoSearchProvider protocol."""

    def __init__(self, client: YouTubeClient) -> None:
        self._client = client

    def search_trending(self, niche: str, days_back: int = 7, limit: int = 20) -> list[VideoResult]:
        """Search for trending YouTube videos in a niche."""
        try:
            items = self._client.search_videos(
                query=niche,
                max_results=min(limit, 50),
                order="viewCount",
            )
            return [_item_to_video_result(item) for item in items]
        except Exception:
            logger.exception("YouTubeProvider.search_trending failed for niche='%s'", niche)
            return []

    def search_videos(self, query: str, max_results: int = 25) -> list[VideoResult]:
        """Search YouTube videos by query."""
        try:
            items = self._client.search_videos(query=query, max_results=max_results)
            return [_item_to_video_result(item) for item in items]
        except Exception:
            logger.exception("YouTubeProvider.search_videos failed for query='%s'", query)
            return []

    def get_channel_videos(self, channel_id: str, max_results: int = 25) -> list[VideoResult]:
        """Get recent videos from a YouTube channel."""
        try:
            items = self._client.get_channel_videos(channel_id=channel_id, max_results=max_results)
            return [_item_to_video_result(item) for item in items]
        except Exception:
            logger.exception("YouTubeProvider.get_channel_videos failed for channel_id='%s'", channel_id)
            return []

    def analyze_competitors(self, channel_ids: list[str]) -> dict[str, Any]:
        """Analyze competitor YouTube channels for content patterns and gaps."""
        results: dict[str, Any] = {}
        for channel_id in channel_ids:
            try:
                stats = self._client.get_channel_stats(channel_id)
                videos = self._client.get_channel_videos(channel_id, max_results=10)

                channel_stats = stats.get("statistics", {})
                snippet = stats.get("snippet", {})

                results[channel_id] = {
                    "channel_name": snippet.get("title", ""),
                    "subscriber_count": int(channel_stats.get("subscriberCount", 0)),
                    "total_videos": int(channel_stats.get("videoCount", 0)),
                    "total_views": int(channel_stats.get("viewCount", 0)),
                    "recent_video_titles": [
                        v.get("snippet", {}).get("title", "") for v in videos[:10]
                    ],
                }
            except Exception:
                logger.warning("Failed to analyze competitor channel_id='%s'", channel_id)
                results[channel_id] = {"error": "failed to fetch"}

        return results
