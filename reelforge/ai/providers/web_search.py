from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from ***REMOVED***.services.tavily.client import TavilyResearchClient

logger = logging.getLogger("***REMOVED***.ai.providers.web_search")


class TavilyProvider:
    """WebSearchProvider backed by Tavily AI search.

    Satisfies the WebSearchProvider protocol. Wraps raw Tavily results
    into the standard research dict expected by agents:
        query, answer, key_facts, statistics, expert_quotes,
        common_misconceptions, sources, confidence.
    """

    def __init__(self, client: TavilyResearchClient) -> None:
        self._client = client

    def research(self, topic: str, depth: str = "deep") -> dict[str, Any]:
        """Research a topic using Tavily and return structured data.

        Args:
            topic: The query / topic to research.
            depth: "deep" → advanced Tavily search; "quick" → basic.

        Returns:
            Dict with keys: query, answer, key_facts, statistics,
            expert_quotes, common_misconceptions, sources, confidence.
        """
        try:
            raw = self._client.research(topic=topic, depth=depth)
        except Exception as exc:
            logger.warning(
                "TavilyProvider.research failed for topic='%s': %s",
                topic,
                exc,
                extra={"topic": topic, "error": str(exc)},
            )
            return {
                "query": topic,
                "answer": "",
                "key_facts": [],
                "statistics": [],
                "expert_quotes": [],
                "common_misconceptions": [],
                "sources": [],
                "confidence": "LOW",
                "error": str(exc),
            }

        results: list[dict[str, Any]] = raw.get("results", [])
        answer: str = raw.get("answer") or ""

        sources = [{"url": r.get("url", ""), "title": r.get("title", "")} for r in results if r.get("url")]

        # Use Tavily result content snippets as key facts (capped to 300 chars each)
        key_facts = [r["content"][:300] for r in results[:6] if r.get("content")]

        if len(results) >= 5:  # noqa: PLR2004
            confidence = "HIGH"
        elif len(results) >= 2:  # noqa: PLR2004
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        result: dict[str, Any] = {
            "query": topic,
            "answer": answer,
            "key_facts": key_facts,
            "statistics": [],
            "expert_quotes": [],
            "common_misconceptions": [],
            "sources": sources,
            "confidence": confidence,
        }

        logger.info(
            "TavilyProvider research completed",
            extra={
                "topic": topic,
                "result_count": len(results),
                "source_count": len(sources),
                "has_answer": bool(answer),
                "confidence": confidence,
            },
        )

        return result
