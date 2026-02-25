from __future__ import annotations

import logging
from typing import Any

import httpx

from ***REMOVED***.services.hackernews.exceptions import HackerNewsAPIError

logger = logging.getLogger("***REMOVED***.hackernews.client")

_BASE_URL = "https://hn.algolia.com/api/v1"


class HackerNewsClient:
    """Client for the HackerNews Algolia Search API (no auth required)."""

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{_BASE_URL}/{path}"
        try:
            response = httpx.get(url, params=params, timeout=self._timeout)
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            msg = f"HackerNews API error {exc.response.status_code} for {url}: {exc}"
            raise HackerNewsAPIError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"HackerNews request failed for {url}: {exc}"
            raise HackerNewsAPIError(msg) from exc

    def _hit_to_dict(self, hit: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": hit.get("title") or hit.get("story_title") or "",
            "points": hit.get("points") or 0,
            "num_comments": hit.get("num_comments") or 0,
            "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
            "created_at": hit.get("created_at") or "",
            "objectID": hit.get("objectID") or "",
        }

    def search_stories(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search HN stories by keyword, sorted by relevance."""
        try:
            data = self._get("search", {"query": query, "tags": "story", "hitsPerPage": limit})
            return [self._hit_to_dict(h) for h in data.get("hits", [])]
        except HackerNewsAPIError:
            raise
        except Exception as exc:
            msg = f"search_stories failed for query='{query}': {exc}"
            raise HackerNewsAPIError(msg) from exc

    def search_ask_hn(self, topic: str, limit: int = 15) -> list[dict[str, Any]]:
        """Search Ask HN posts — real community questions about a topic."""
        try:
            data = self._get("search", {"query": topic, "tags": "ask_hn", "hitsPerPage": limit})
            return [self._hit_to_dict(h) for h in data.get("hits", [])]
        except HackerNewsAPIError:
            raise
        except Exception as exc:
            msg = f"search_ask_hn failed for topic='{topic}': {exc}"
            raise HackerNewsAPIError(msg) from exc

    def get_recent_stories(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent HN stories by date (useful for rising-topic signals)."""
        try:
            data = self._get(
                "search_by_date",
                {"query": query, "tags": "story", "hitsPerPage": limit},
            )
            return [self._hit_to_dict(h) for h in data.get("hits", [])]
        except HackerNewsAPIError:
            raise
        except Exception as exc:
            msg = f"get_recent_stories failed for query='{query}': {exc}"
            raise HackerNewsAPIError(msg) from exc
