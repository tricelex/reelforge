from __future__ import annotations

from pydantic_ai import Agent

translation_agent: Agent[None, str] = Agent(
    "anthropic:claude-sonnet-4-5",
    retries=2,
)
