from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any

from reelforge.agents.schemas import VideoResult

if TYPE_CHECKING:
    from reelforge.services.serpapi.client import SerpApiClient

logger = logging.getLogger("reelforge.agents.providers.youtube")


def _parse_duration_from_str(duration_str: str) -> int | None:
    """Parse a duration string like '10:23' or '1:02:45' to total seconds."""
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


def _parse_views(views: Any) -> int | None:
    """Parse views from int, str, or None."""
    if views is None:
        return None
    if isinstance(views, int):
        return views
    try:
        cleaned = str(views).replace(",", "").strip()
        return int(cleaned)
    except (ValueError, AttributeError):
        return None


def _video_dict_to_result(item: dict[str, Any]) -> VideoResult:
    return VideoResult(
        title=item.get("title", ""),
        url=item.get("url", ""),
        channel=item.get("channel_name", ""),
        channel_id=item.get("channel_id", ""),
        channel_handle=item.get("channel_handle", ""),
        views=_parse_views(item.get("views")),
        likes=None,
        published_at=item.get("published_date"),
        duration_seconds=item.get("duration_seconds"),
    )


class SerpApiYouTubeProvider:
    """VideoSearchProvider backed by SerpAPI YouTube engine."""

    def __init__(self, client: SerpApiClient) -> None:
        self._client = client

    def search_trending(self, niche: str, days_back: int = 7, limit: int = 20) -> list[VideoResult]:
        """Search for trending YouTube videos in a niche."""
        try:
            items = self._client.search_videos(query=niche, max_results=limit)
            return [_video_dict_to_result(item) for item in items]
        except Exception:
            logger.exception("SerpApiYouTubeProvider.search_trending failed for niche='%s'", niche)
            return []

    def search_videos(self, query: str, max_results: int = 25) -> list[VideoResult]:
        """Search YouTube videos by query."""
        try:
            items = self._client.search_videos(query=query, max_results=max_results)
            return [_video_dict_to_result(item) for item in items]
        except Exception:
            logger.exception("SerpApiYouTubeProvider.search_videos failed for query='%s'", query)
            return []

    def get_channel_videos(self, channel_id: str, max_results: int = 25) -> list[VideoResult]:
        """Get recent videos from a YouTube channel by searching for its channel page."""
        try:
            if channel_id.startswith("@"):
                handle = channel_id.lstrip("@")
                items = self._client.search_videos(
                    query=f"site:youtube.com/@{handle}",
                    max_results=max_results,
                )
                matched = [item for item in items if handle.lower() in item.get("channel_url", "").lower()]
            else:
                items = self._client.search_videos(
                    query=f"site:youtube.com/channel/{channel_id}",
                    max_results=max_results,
                )
                matched = [item for item in items if item.get("channel_id") == channel_id]
            return [_video_dict_to_result(item) for item in matched]
        except Exception:
            logger.exception("SerpApiYouTubeProvider.get_channel_videos failed for channel_id='%s'", channel_id)
            return []

    def analyze_competitors(self, channel_ids: list[str]) -> dict[str, Any]:
        """Analyze competitor YouTube channels for content patterns."""
        results: dict[str, Any] = {}
        seen: set[str] = set()
        for identifier in channel_ids:
            if not identifier or identifier in seen:
                continue
            seen.add(identifier)
            try:
                data = self._client.search_channel_with_videos(query=identifier)
                results[identifier] = {
                    "channel_name": data["channel_name"],
                    "channel_handle": data["channel_handle"],
                    "channel_url": data["channel_url"],
                    "subscriber_count": data["subscriber_count"],
                    "recent_video_titles": data["recent_video_titles"],
                }
            except Exception:  # noqa: BLE001
                logger.warning(
                    "SerpApiYouTubeProvider.analyze_competitors failed for identifier='%s'",
                    identifier,
                )
                results[identifier] = {"error": "failed to fetch"}

        return results
