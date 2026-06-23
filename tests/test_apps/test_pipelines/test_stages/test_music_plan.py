"""Tests for the music_plan stage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.music_plan import MusicPlanStage


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.prompt_snapshot = {}
    ctx.channel.id = 'channel-uuid'
    ctx.channel.niche_config = MagicMock()
    ctx.channel.niche_config.music_mood_map = {'intro': ['tense', 'hopeful']}
    ctx.upstream = {
        'outline': {
            'chapters': [
                {
                    'idx': 0,
                    'title': 'Intro',
                    'device': 'open_loop',
                    'target_seconds': 120,
                    'thesis': 'hook',
                },
            ],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    return ctx


def test_music_plan_stage_key() -> None:
    """MusicPlanStage has the expected class attributes."""
    assert MusicPlanStage.key == 'music_plan'
    assert MusicPlanStage.queue == 'api'


def test_music_plan_fan_out_none() -> None:
    """music_plan is a single-execution stage."""
    assert MusicPlanStage().fan_out(MagicMock()) is None


def test_music_plan_run_returns_entries() -> None:
    """run() returns dict with 'entries' list from LLM output."""
    from server.apps.pipelines.schemas import (
        MusicEntry,
        MusicPlanOutput,
    )

    ctx = _make_ctx()
    fake_output = MusicPlanOutput(
        entries=[
            MusicEntry(
                chapter_idx=0,
                library_asset_id='lib-uuid',
                gain_db=-3.0,
            ),
        ],
    )

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.llm.run_agent',
                new=AsyncMock(return_value=fake_output),
            ),
            patch(
                'server.apps.pipelines.stages.music_plan._fetch_music_library',
                new=AsyncMock(
                    return_value=[
                        {
                            'id': 'lib-uuid',
                            'name': 'Tense Track',
                            'tags': ['tense'],
                            'meta': {},
                        },
                    ],
                ),
            ),
        ):
            return await MusicPlanStage().run(ctx)

    result = asyncio.run(_inner())
    assert 'entries' in result
    assert result['entries'][0]['chapter_idx'] == 0  # type: ignore[index]


def test_fetch_music_library_returns_empty_list_when_no_assets() -> None:
    """_fetch_music_library returns [] when the queryset yields no results."""
    from server.apps.pipelines.stages.music_plan import (
        _fetch_music_library,
    )

    async def _empty():  # pragma: no cover
        return
        yield  # makes this an async generator

    ordered = MagicMock()
    ordered.__getitem__.return_value = _empty()
    qs = MagicMock()
    qs.__or__.return_value.order_by.return_value = ordered

    async def _inner() -> list[dict[str, object]]:
        with patch(
            'server.apps.assets.models.LibraryAsset.objects.filter',
            return_value=qs,
        ):
            return await _fetch_music_library('channel-uuid')

    result = asyncio.run(_inner())
    assert result == []


def test_fetch_music_library_returns_asset_dicts() -> None:
    """_fetch_music_library returns list of asset dicts when assets exist."""
    from server.apps.pipelines.stages.music_plan import (
        _fetch_music_library,
    )

    mock_asset = MagicMock()
    mock_asset.id = 'lib-asset-uuid'
    mock_asset.name = 'Epic Orchestra'
    mock_asset.tags = ['epic', 'orchestral']
    mock_asset.meta = {'bpm': 140}

    async def _one_asset():
        yield mock_asset

    ordered = MagicMock()
    ordered.__getitem__.return_value = _one_asset()
    qs = MagicMock()
    qs.__or__.return_value.order_by.return_value = ordered

    async def _inner() -> list[dict[str, object]]:
        with patch(
            'server.apps.assets.models.LibraryAsset.objects.filter',
            return_value=qs,
        ):
            return await _fetch_music_library('channel-uuid')

    result = asyncio.run(_inner())
    assert result == [
        {
            'id': 'lib-asset-uuid',
            'name': 'Epic Orchestra',
            'tags': ['epic', 'orchestral'],
            'meta': {'bpm': 140},
        },
    ]
