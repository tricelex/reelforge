from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("reelforge.services.tavily")


class TavilyResearchClient:
    """Tavily AI search client for deep web research.

    Wraps the tavily-python SDK. Returns raw Tavily response dicts —
    synthesis and structuring are the TavilyProvider's responsibility.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def research(
        self,
        topic: str,
        depth: str = "deep",
    ) -> dict[str, Any]:
        """Run a Tavily search and return the raw response.

        Args:
            topic: The search query / topic to research.
            depth: "deep" → advanced search_depth; "quick" → basic search_depth.

        Returns:
            Raw Tavily response dict with keys:
                query, answer, results, images, follow_up_questions, response_time, usage.

        Raises:
            Exception: Propagates any Tavily SDK errors to the caller.
        """
        from tavily import TavilyClient

        client = TavilyClient(self._api_key)
        search_depth = "advanced" if depth == "deep" else "basic"

        response: dict[str, Any] = client.search(
            query=topic,
            search_depth=search_depth,
            include_answer="advanced",
        )

        logger.debug(
            "Tavily search completed",
            extra={
                "topic": topic,
                "result_count": len(response.get("results", [])),
                "has_answer": bool(response.get("answer")),
                "response_time": response.get("response_time"),
            },
        )

        return response
