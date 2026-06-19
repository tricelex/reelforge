"""Tests for the outline stage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.outline import OutlineStage


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.topic = 'The fall of Rome'
    ctx.run.prompt_snapshot = {}
    ctx.channel.niche_config = MagicMock()
    ctx.channel.niche_config.format = MagicMock()
    ctx.channel.niche_config.format.beats = [
        {'key': 'intro', 'pct': 0.1, 'purpose': 'hook'},
        {'key': 'main', 'pct': 0.8, 'purpose': 'story'},
        {'key': 'outro', 'pct': 0.1, 'purpose': 'cta'},
    ]
    ctx.channel.wpm = 158
    ctx.upstream = {
        'research': {
            'brief': {
                'topic': 'The fall of Rome',
                'key_facts': ['Rome fell in 476 AD'],
                'narrative_angles': ['economic decline'],
                'hooks': ['What really ended Rome?'],
                'sources': [],
            },
            'sources': [],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    return ctx


def test_outline_stage_key() -> None:
    """OutlineStage has the expected class attributes."""
    assert OutlineStage.key == 'outline'
    assert OutlineStage.queue == 'api'


def test_outline_fan_out_none() -> None:
    """Outline is a single-execution stage."""
    assert OutlineStage().fan_out(MagicMock()) is None


def test_outline_run_returns_chapters() -> None:
    """run() returns dict with 'chapters' and 'total_target_seconds'."""
    from server.apps.pipelines.schemas import (
        Chapter,
        OutlineOutput,
    )

    ctx = _make_ctx()
    fake_output = OutlineOutput(
        chapters=[
            Chapter(
                idx=0,
                title='The Beginning',
                thesis='Rome rose fast.',
                target_seconds=120,
                device='open_loop',
            ),
            Chapter(
                idx=1,
                title='The Fall',
                thesis='Rome fell slow.',
                target_seconds=900,
                device='tension_build',
            ),
        ],
        total_target_seconds=1020,
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ):
            return await OutlineStage().run(ctx)

    result = asyncio.run(_inner())
    assert 'chapters' in result
    assert len(result['chapters']) == 2
    assert result['total_target_seconds'] == 1020


def test_outline_run_with_no_niche_config() -> None:
    """run() works when channel.niche_config is None (no beats)."""
    from server.apps.pipelines.schemas import (
        Chapter,
        OutlineOutput,
    )

    ctx = MagicMock()
    ctx.run.topic = 'Ancient Egypt'
    ctx.channel.niche_config = None
    ctx.upstream = {'research': {'brief': {}, 'sources': []}}
    ctx.config = {'total_target_seconds': 600}
    ctx.costs = AsyncMock()
    ctx.prompts.render = AsyncMock(return_value=('', ''))

    fake_output = OutlineOutput(
        chapters=[
            Chapter(
                idx=0,
                title='Intro',
                thesis='Egypt.',
                target_seconds=60,
                device='open_loop',
            ),
        ],
        total_target_seconds=600,
    )

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.generation.clients.llm.run_agent',
            new=AsyncMock(return_value=fake_output),
        ):
            return await OutlineStage().run(ctx)

    result = asyncio.run(_inner())
    assert 'chapters' in result
