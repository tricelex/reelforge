from __future__ import annotations

import logging
from typing import Any

from reelforge.services.exploding_topics.exceptions import ExplodingTopicsAPIError

logger = logging.getLogger("reelforge.exploding_topics.client")

# Exploding Topics does not have a stable public API.
# This client is a properly-structured stub. Real data requires either:
# 1. Paid API access (contact explodintopics.com for enterprise)
# 2. Web scraping (legally complex, fragile)
# TODO: Implement when API access is obtained.
_STUB_TOPICS: dict[str, list[dict[str, Any]]] = {
    "technology": [
        {
            "keyword": "AI agents",
            "growth_rate": "2500%",
            "category": "technology",
            "description": "Autonomous AI software agents",
        },
        {
            "keyword": "vibe coding",
            "growth_rate": "1800%",
            "category": "technology",
            "description": "AI-assisted programming workflow",
        },
    ],
    "finance": [
        {
            "keyword": "micro-investing",
            "growth_rate": "450%",
            "category": "finance",
            "description": "Investing small amounts via apps",
        },
        {
            "keyword": "treasury bills",
            "growth_rate": "380%",
            "category": "finance",
            "description": "Short-term government debt instruments",
        },
    ],
    "health": [
        {
            "keyword": "glucose monitoring",
            "growth_rate": "620%",
            "category": "health",
            "description": "Continuous glucose monitoring for non-diabetics",
        },
        {
            "keyword": "cold plunge",
            "growth_rate": "890%",
            "category": "health",
            "description": "Cold water immersion therapy",
        },
    ],
    "default": [
        {
            "keyword": "AI automation",
            "growth_rate": "1200%",
            "category": "general",
            "description": "AI-powered workflow automation",
        },
        {
            "keyword": "passive income",
            "growth_rate": "340%",
            "category": "general",
            "description": "Income streams requiring minimal effort",
        },
    ],
}


class ExplodingTopicsClient:
    """Stub client for Exploding Topics trend discovery.

    Exploding Topics has no stable public API. This stub returns
    representative placeholder data with the correct interface.
    Real scraping/API integration is deferred pending API access.
    """

    def __init__(self) -> None:
        logger.info(
            "ExplodingTopicsClient initialized (stub — no public API available). Returning placeholder topic data."
        )

    def get_rising(self, category: str = "") -> list[dict[str, Any]]:
        """Get rising topics for a category.

        Args:
            category: Topic category filter (e.g. "technology", "finance", "health")

        Returns:
            List of rising topic dicts with keyword, growth_rate, category, description

        TODO: Replace with real Exploding Topics API call when API access is available.
        """
        try:
            normalized = category.lower().strip()
            topics = _STUB_TOPICS.get(normalized, _STUB_TOPICS["default"])
            logger.warning(
                "ExplodingTopicsClient.get_rising returning stub data for category='%s'",
                category,
            )
            return [dict(t) for t in topics]
        except Exception as exc:
            msg = f"ExplodingTopics get_rising failed: {exc}"
            raise ExplodingTopicsAPIError(msg) from exc
