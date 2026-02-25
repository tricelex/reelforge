from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from reelforge.services.perplexity.client import PerplexityClient

logger = logging.getLogger("reelforge.agents.providers.web_search")


class PerplexityProvider:
    """Provider that wraps PerplexityClient and satisfies WebSearchProvider protocol."""

    def __init__(self, client: PerplexityClient) -> None:
        self._client = client

    def research(self, topic: str, depth: str = "deep") -> dict[str, Any]:
        """Research a topic using Perplexity AI with web grounding."""
        try:
            return self._client.research(topic=topic, depth=depth)
        except Exception as exc:
            logger.warning("PerplexityProvider.research failed for topic='%s': %s", topic, exc)
            return {
                "query": topic,
                "answer": "",
                "sources": [],
                "error": "research failed",
            }
