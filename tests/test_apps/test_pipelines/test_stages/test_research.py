"""Tests for the research stage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.research import ResearchStage


def _make_ctx(topic: str = 'The fall of Rome') -> MagicMock:
    ctx = MagicMock()
    ctx.run.topic = topic
    ctx.run.prompt_snapshot = {}
    ctx.channel.niche_config = MagicMock()
    ctx.channel.niche_config.audience = 'history enthusiasts'
    ctx.channel.niche_config.angle = 'factual'
    ctx.execution.shard_index = None
    ctx.upstream = {}
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.assets = AsyncMock()
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    return ctx


def test_research_stage_key() -> None:
    """ResearchStage has the expected class attributes."""
    assert ResearchStage.key == 'research'
    assert ResearchStage.queue == 'api'
    assert ResearchStage.max_retries == 3


def test_research_fan_out_returns_none() -> None:
    """Research is a single-execution stage; fan_out must return None."""
    assert ResearchStage().fan_out(_make_ctx()) is None


def test_research_run_returns_brief_and_sources() -> None:
    """run() returns a dict with 'brief' and 'sources' keys."""
    from server.apps.pipelines.schemas import (
        ResearchBrief,
        ResearchOutput,
    )

    ctx = _make_ctx()
    fake_output = ResearchOutput(
        brief=ResearchBrief(
            topic='The fall of Rome',
            key_facts=['Rome fell in 476 AD'],
            sources=[],
            narrative_angles=['economic decline'],
            hooks=['What really ended Rome?'],
        ),
        sources=[],
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ):
            return await ResearchStage().run(ctx)

    result = asyncio.run(_inner())
    assert 'brief' in result
    assert 'sources' in result
    assert result['brief']['topic'] == 'The fall of Rome'
