from __future__ import annotations

import logging
from typing import Any

import httpx

from reelforge.services.perplexity.exceptions import PerplexityAPIError
from reelforge.services.perplexity.exceptions import PerplexityAuthError
from reelforge.services.perplexity.exceptions import PerplexityQuotaError

logger = logging.getLogger("reelforge.perplexity.client")

_PERPLEXITY_BASE_URL = "https://api.perplexity.ai"
_SONAR_MODEL = "sonar"


class PerplexityClient:
    """Perplexity AI client for web-grounded research using httpx."""

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key
        self._client = httpx.Client(
            base_url=_PERPLEXITY_BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    def _handle_errors(self, response: httpx.Response) -> None:
        if response.status_code == 200:
            return
        if response.status_code == 401:
            msg = f"Perplexity API authentication failed: {response.text}"
            raise PerplexityAuthError(msg)
        if response.status_code == 429:
            msg = "Perplexity API rate limit exceeded"
            raise PerplexityQuotaError(msg)
        msg = f"Perplexity API error: {response.text}"
        raise PerplexityAPIError(
            msg,
            status_code=response.status_code,
        )

    def research_topic(self, topic: str, depth: str = "deep") -> dict[str, Any]:
        """Research a topic using Perplexity's sonar model with web grounding.

        Args:
            topic: Topic or question to research
            depth: Research depth — "quick", "standard", or "deep" (affects system prompt)

        Returns:
            Dict with answer, sources, and raw response data
        """
        system_prompt = (
            "You are a research assistant. Provide factual, well-sourced information "
            "about the given topic. Include relevant statistics, trends, and expert "
            "perspectives where available. Be concise and accurate."
        )
        if depth == "deep":
            system_prompt += " Provide comprehensive analysis with multiple angles and data points."
        elif depth == "quick":
            system_prompt += " Provide a brief overview focusing on the most important points."

        payload: dict[str, Any] = {
            "model": _SONAR_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": topic},
            ],
            "max_tokens": 2048,
            "temperature": 0.2,
            "return_citations": True,
        }

        try:
            response = self._client.post("/chat/completions", json=payload)
            self._handle_errors(response)
            data = response.json()

            choices = data.get("choices", [])
            answer = choices[0]["message"]["content"] if choices else ""
            citations = data.get("citations", [])

            return {
                "query": topic,
                "answer": answer,
                "sources": [{"url": url} for url in citations],
                "model": data.get("model", _SONAR_MODEL),
                "usage": data.get("usage", {}),
            }
        except (PerplexityAuthError, PerplexityQuotaError, PerplexityAPIError):
            raise
        except Exception as exc:
            msg = f"Perplexity research_topic failed for '{topic}': {exc}"
            raise PerplexityAPIError(msg) from exc

    def research(self, topic: str, depth: str = "deep") -> dict[str, Any]:
        """Research a topic with specified depth (alias for research_topic)."""
        return self.research_topic(topic=topic, depth=depth)
