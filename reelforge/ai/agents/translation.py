from __future__ import annotations

from pydantic_ai import Agent

translation_agent: Agent[None, str] = Agent(
    retries=2,
)
