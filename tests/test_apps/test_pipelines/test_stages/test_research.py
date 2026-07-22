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
    ctx.prompts.get_model = AsyncMock(return_value=None)
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
        ResearchSource,
    )

    ctx = _make_ctx()
    fake_output = ResearchOutput(
        brief=ResearchBrief(
            topic='The fall of Rome',
            key_facts=['Rome fell in 476 AD'],
            sources=[
                ResearchSource(
                    url='https://a.example.com',
                    title='A',
                    key_facts=['Rome fell in 476 AD'],
                ),
                ResearchSource(
                    url='https://b.example.com',
                    title='B',
                    key_facts=['Rome fell in the year 476 AD'],
                ),
            ],
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


def test_research_brief_empty_key_facts_is_allowed() -> None:
    from server.apps.pipelines.schemas import ResearchBrief

    brief = ResearchBrief(
        topic='Rome',
        key_facts=[],
        sources=[],
        narrative_angles=[],
        hooks=[],
    )
    assert brief.key_facts == []


def test_research_brief_ignores_empty_source_facts() -> None:
    from server.apps.pipelines.schemas import ResearchBrief, ResearchSource

    brief = ResearchBrief(
        topic='Rome',
        key_facts=['Rome fell in 476 AD'],
        sources=[
            ResearchSource(
                url='https://a.example.com',
                title='A',
                key_facts=['', 'Rome fell in 476 AD'],
            ),
            ResearchSource(
                url='https://b.example.com',
                title='B',
                key_facts=['Rome fell in 476 AD'],
            ),
        ],
        narrative_angles=[],
        hooks=[],
    )
    assert brief.key_facts == ['Rome fell in 476 AD']


def test_research_brief_rejects_majority_uncorroborated_facts() -> None:
    """A brief where most key_facts have < 2 corroborating sources is rejected."""
    import pytest
    from pydantic import ValidationError

    from server.apps.pipelines.schemas import ResearchBrief, ResearchSource

    with pytest.raises(ValidationError, match='corroborat'):
        ResearchBrief(
            topic='Rome',
            key_facts=[
                'Rome fell in 476 AD',
                'Odoacer deposed Romulus Augustulus',
            ],
            sources=[
                ResearchSource(
                    url='https://a.example.com',
                    title='A',
                    key_facts=['Rome fell in 476 AD'],
                ),
            ],
            narrative_angles=[],
            hooks=[],
        )


def test_research_brief_accepts_well_corroborated_facts() -> None:
    from server.apps.pipelines.schemas import ResearchBrief, ResearchSource

    brief = ResearchBrief(
        topic='Rome',
        key_facts=['Rome fell in 476 AD'],
        sources=[
            ResearchSource(
                url='https://a.example.com',
                title='A',
                key_facts=['Rome fell in 476 AD'],
            ),
            ResearchSource(
                url='https://b.example.com',
                title='B',
                key_facts=['The city of Rome fell in the year 476 AD'],
            ),
        ],
        narrative_angles=[],
        hooks=[],
    )
    assert brief.key_facts == ['Rome fell in 476 AD']
