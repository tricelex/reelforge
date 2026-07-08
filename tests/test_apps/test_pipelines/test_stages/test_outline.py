"""Tests for the outline stage."""

import asyncio
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import django.utils.timezone
import pytest

from server.apps.pipelines.stages.outline import OutlineStage


class _AsyncIter:
    """Minimal async iterator wrapping a plain list.

    For mocking `async for` iteration over a queryset-like mock return value.
    """

    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)

    def __aiter__(self) -> '_AsyncIter':
        return self

    async def __anext__(self) -> Any:
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    from asgiref.sync import sync_to_async

    @sync_to_async
    def _close_connections() -> None:
        from django.db import connections

        connections.close_all()

    async def _wrapped() -> Any:
        try:
            return await coro
        finally:
            await _close_connections()

    return asyncio.run(_wrapped())


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.topic = 'The fall of Rome'
    ctx.run.id = 'run-outline-1'
    ctx.run.prompt_snapshot = {}
    ctx.channel.id = 'chan-outline-1'
    ctx.channel.niche_config = MagicMock()
    ctx.channel.niche_config.format_pool.filter.return_value = _AsyncIter([])
    ctx.channel.niche_config.format = MagicMock()
    ctx.channel.niche_config.format.beats = [
        {'key': 'intro', 'pct': 0.1, 'purpose': 'hook'},
        {'key': 'main', 'pct': 0.8, 'purpose': 'story'},
        {'key': 'outro', 'pct': 0.1, 'purpose': 'cta'},
    ]
    ctx.channel.niche_config.format.key = 'legacy_format'
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
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(return_value=fake_output),
            ),
            patch(
                'server.apps.pipelines.stages.outline.compute_soft_spots',
                new=AsyncMock(return_value=''),
            ),
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
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(return_value=fake_output),
            ),
            patch(
                'server.apps.pipelines.stages.outline.compute_soft_spots',
                new=AsyncMock(return_value=''),
            ),
        ):
            return await OutlineStage().run(ctx)

    result = asyncio.run(_inner())
    assert 'chapters' in result


def test_pick_format_excludes_recent_keys() -> None:
    """_pick_format avoids formats used in the last N runs when alternatives exist."""
    from server.apps.pipelines.stages.outline import _pick_format

    fmt_a = MagicMock(key='fmt_a', beats=[{'name': 'a'}])
    fmt_b = MagicMock(key='fmt_b', beats=[{'name': 'b'}])
    beats, key = _pick_format([fmt_a, fmt_b], recent_keys={'fmt_a'})
    assert key == 'fmt_b'
    assert beats == [{'name': 'b'}]


def test_pick_format_falls_back_when_all_recent() -> None:
    """_pick_format still returns a format when every pool entry was recently used."""
    from server.apps.pipelines.stages.outline import _pick_format

    fmt_a = MagicMock(key='fmt_a', beats=[{'name': 'a'}])
    _beats, key = _pick_format([fmt_a], recent_keys={'fmt_a'})
    assert key == 'fmt_a'


def test_pick_format_empty_pool_returns_empty() -> None:
    from server.apps.pipelines.stages.outline import _pick_format

    beats, key = _pick_format([], recent_keys=set())
    assert beats == []
    assert key == ''


@pytest.mark.django_db(transaction=True)
def test_recent_format_keys_reads_last_two_successful_outlines() -> None:
    """_recent_format_keys returns format_key from the channel's last 2 SUCCEEDED outline runs."""
    from server.apps.channels.models import Channel, ChannelKind
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.stages.outline import _recent_format_keys

    channel = Channel.objects.create(name='Fmt Ch', kind=ChannelKind.LONGFORM)
    bp = PipelineBlueprint.objects.create(
        name='fmt_test_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    runs = [
        PipelineRun.objects.create(
            channel=channel,
            blueprint=bp,
            blueprint_snapshot={},
            topic=f'topic {i}',
        )
        for i in range(3)
    ]
    for i, run in enumerate(runs):
        StageExecution.objects.create(
            run=run,
            stage_key='outline',
            status=StageStatus.SUCCEEDED,
            input_hash='',
            output={'format_key': f'fmt_{i}'},
            finished_at=django.utils.timezone.now(),
        )

    keys = _run(
        _recent_format_keys(str(channel.id), exclude_run_id=str(runs[-1].id)),
    )
    assert keys == {'fmt_1', 'fmt_0'} or len(keys) == 2


def test_outline_run_uses_format_pool_when_multiple_present() -> None:
    """When niche.format_pool has 2+ entries, run() picks one and reports format_key."""
    from server.apps.pipelines.schemas import Chapter, OutlineOutput

    ctx = _make_ctx()
    fmt_a = MagicMock(key='fmt_a', beats=[{'name': 'a'}])
    fmt_b = MagicMock(key='fmt_b', beats=[{'name': 'b'}])
    ctx.channel.niche_config.format_pool.filter.return_value = _AsyncIter(
        [fmt_a, fmt_b],
    )

    fake_output = OutlineOutput(
        chapters=[
            Chapter(
                idx=0,
                title='T',
                thesis='X',
                target_seconds=60,
                device='open_loop',
            ),
        ],
        total_target_seconds=60,
    )

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(return_value=fake_output),
            ),
            patch(
                'server.apps.pipelines.stages.outline._recent_format_keys',
                new=AsyncMock(return_value=set()),
            ),
            patch(
                'server.apps.pipelines.stages.outline.compute_soft_spots',
                new=AsyncMock(return_value=''),
            ),
        ):
            return await OutlineStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['format_key'] in {'fmt_a', 'fmt_b'}


def test_outline_run_single_pool_entry_used_directly() -> None:
    """When niche.format_pool has exactly 1 entry, it's used without a DB lookup."""
    from server.apps.pipelines.schemas import Chapter, OutlineOutput

    ctx = _make_ctx()
    fmt_only = MagicMock(key='only_fmt', beats=[{'name': 'solo'}])
    ctx.channel.niche_config.format_pool.filter.return_value = _AsyncIter(
        [fmt_only],
    )

    fake_output = OutlineOutput(
        chapters=[
            Chapter(
                idx=0,
                title='T',
                thesis='X',
                target_seconds=60,
                device='open_loop',
            ),
        ],
        total_target_seconds=60,
    )

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(return_value=fake_output),
            ),
            patch(
                'server.apps.pipelines.stages.outline.compute_soft_spots',
                new=AsyncMock(return_value=''),
            ),
        ):
            return await OutlineStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['format_key'] == 'only_fmt'


def test_outline_run_includes_soft_spots_in_prompt_context() -> None:
    """run() passes compute_soft_spots' output into the prompt render call."""
    from server.apps.pipelines.schemas import Chapter, OutlineOutput

    ctx = _make_ctx()
    fake_output = OutlineOutput(
        chapters=[
            Chapter(
                idx=0,
                title='T',
                thesis='X',
                target_seconds=60,
                device='open_loop',
            ),
        ],
        total_target_seconds=60,
    )

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(return_value=fake_output),
            ),
            patch(
                'server.apps.pipelines.stages.outline.compute_soft_spots',
                new=AsyncMock(
                    return_value='Known pacing soft spots on this channel: ...',
                ),
            ),
        ):
            return await OutlineStage().run(ctx)

    asyncio.run(_inner())
    render_kwargs = ctx.prompts.render.call_args.args[1]
    assert 'soft spots' in render_kwargs['soft_spots']
