"""Tests for the assembly pipeline stage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.channels.models import Channel, ChannelKind
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    StageExecution,
    StageStatus,
)
from server.apps.pipelines.stages.assembly import (
    AssemblyStage,
    _build_chapter_audio_map,
    _build_music_map,
    _build_scene_asset_map,
    _group_scenes_by_chapter,
)


def test_assembly_stage_attributes() -> None:
    assert AssemblyStage.key == 'assembly'
    assert AssemblyStage.queue == 'render'
    assert AssemblyStage.max_retries == 1
    assert AssemblyStage.timeout_s == 3600


def test_assembly_fan_out_returns_none() -> None:
    assert AssemblyStage().fan_out(MagicMock()) is None


def test_group_scenes_by_chapter() -> None:
    scenes = [
        {'chapter_idx': 0, 'segment_idx': 0, 'start_s': 0.0, 'end_s': 5.0},
        {'chapter_idx': 0, 'segment_idx': 1, 'start_s': 5.0, 'end_s': 10.0},
        {'chapter_idx': 1, 'segment_idx': 0, 'start_s': 0.0, 'end_s': 7.0},
    ]
    result = _group_scenes_by_chapter(scenes)
    assert list(result.keys()) == [0, 1]
    assert len(result[0]) == 2
    assert len(result[1]) == 1


def test_build_music_map() -> None:
    entries = [
        {'chapter_idx': 0, 'library_asset_id': 'uuid-a', 'gain_db': -3.0},
        {'chapter_idx': 1, 'library_asset_id': 'uuid-b', 'gain_db': -6.0},
    ]
    result = _build_music_map(entries)
    assert result[0]['library_asset_id'] == 'uuid-a'
    assert result[1]['gain_db'] == -6.0


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.id = 'run-uuid'
    ctx.upstream = {
        'motion': {'shards': [{'shard_index': 0, 'status': 'SUCCEEDED'}]},
        'tts': {'shards': [{'shard_index': 0, 'status': 'SUCCEEDED'}]},
        'alignment': {
            'scenes': [
                {
                    'chapter_idx': 0,
                    'segment_idx': 0,
                    'start_s': 0.0,
                    'end_s': 5.0,
                    'text': 'Hi',
                    'words': [],
                    'scene_idx': 0,
                },
            ],
            'ass_asset_id': 'sub-uuid',
        },
        'music_plan': {
            'entries': [
                {
                    'chapter_idx': 0,
                    'library_asset_id': 'music-uuid',
                    'gain_db': -3.0,
                }
            ],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.assets = AsyncMock()
    ctx.assets.save = AsyncMock(return_value=MagicMock(id='final-uuid'))
    ctx.channel.branding = None
    return ctx


def test_assembly_run_returns_asset_id_and_duration() -> None:
    """AssemblyStage.run() saves FINAL_VIDEO and returns asset_id + duration_s."""
    ctx = _make_ctx()
    fake_probe = {'format': {'duration': '15.5'}, 'streams': []}

    async def _run() -> dict:  # type: ignore[type-arg]
        with (
            patch(
                'server.apps.pipelines.stages.assembly._build_scene_asset_map',
                new=AsyncMock(return_value={0: 'vid-uuid-0'}),
            ),
            patch(
                'server.apps.pipelines.stages.assembly._build_chapter_audio_map',
                new=AsyncMock(return_value={0: 'audio-uuid-0'}),
            ),
            patch(
                'server.apps.pipelines.stages.assembly._fetch_asset_bytes',
                new=AsyncMock(return_value=b'fake-bytes'),
            ),
            patch(
                'server.apps.pipelines.stages.assembly._fetch_library_bytes',
                new=AsyncMock(return_value=b'fake-music'),
            ),
            patch('server.apps.rendering.ffmpeg.mux_scene', new=AsyncMock()),
            patch(
                'server.apps.rendering.ffmpeg.concat_chapter',
                new=AsyncMock(),
            ),
            patch('server.apps.rendering.ffmpeg.final_pass', new=AsyncMock()),
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(return_value=fake_probe),
            ),
            patch(
                'asyncio.to_thread',
                new=AsyncMock(return_value=b'final-video'),
            ),
        ):
            return await AssemblyStage().run(ctx)

    result = asyncio.run(_run())
    assert result['asset_id'] == 'final-uuid'
    assert result['duration_s'] == 15.5


def test_assembly_run_calls_final_pass_with_watermark_when_branding_set() -> None:
    """AssemblyStage passes watermark_path to final_pass when branding exists."""
    ctx = _make_ctx()
    branding = MagicMock()
    branding.watermark = MagicMock(id='wm-uuid')
    branding.watermark_opacity = 0.7
    ctx.channel.branding = branding
    fake_probe = {'format': {'duration': '15.5'}, 'streams': []}
    final_pass_calls: list[dict] = []  # type: ignore[type-arg]

    async def fake_final_pass(**kwargs: object) -> None:
        final_pass_calls.append(dict(kwargs))

    async def _run() -> None:
        with (
            patch(
                'server.apps.pipelines.stages.assembly._build_scene_asset_map',
                new=AsyncMock(return_value={0: 'vid-0'}),
            ),
            patch(
                'server.apps.pipelines.stages.assembly._build_chapter_audio_map',
                new=AsyncMock(return_value={0: 'audio-0'}),
            ),
            patch(
                'server.apps.pipelines.stages.assembly._fetch_asset_bytes',
                new=AsyncMock(return_value=b'bytes'),
            ),
            patch(
                'server.apps.pipelines.stages.assembly._fetch_library_bytes',
                new=AsyncMock(return_value=b'wm'),
            ),
            patch('server.apps.rendering.ffmpeg.mux_scene', new=AsyncMock()),
            patch(
                'server.apps.rendering.ffmpeg.concat_chapter',
                new=AsyncMock(),
            ),
            patch(
                'server.apps.rendering.ffmpeg.final_pass',
                new=AsyncMock(side_effect=fake_final_pass),
            ),
            patch(
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(return_value=fake_probe),
            ),
            patch(
                'asyncio.to_thread',
                new=AsyncMock(return_value=b'final'),
            ),
        ):
            await AssemblyStage().run(ctx)

    asyncio.run(_run())
    assert len(final_pass_calls) == 1
    assert final_pass_calls[0]['watermark_path'] is not None


def _run_async(coro: object) -> object:
    """Run a coroutine, closing Django DB connections on exit."""
    from asgiref.sync import sync_to_async  # noqa: PLC0415
    from collections.abc import Coroutine  # noqa: PLC0415
    from typing import Any  # noqa: PLC0415

    @sync_to_async
    def _close() -> None:
        from django.db import connections  # noqa: PLC0415

        connections.close_all()

    async def _wrapped() -> Any:
        try:
            return await coro  # type: ignore[misc]
        finally:
            await _close()

    return asyncio.run(_wrapped())


@pytest.mark.django_db(transaction=True)
def test_build_scene_asset_map_queries_motion_children() -> None:
    """_build_scene_asset_map reads scene_idx+asset_id from motion children."""
    channel = Channel.objects.create(
        name='Asm DB Ch', kind=ChannelKind.LONGFORM
    )
    bp = PipelineBlueprint.objects.create(
        name='asm_db_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {'key': 'assembly', 'depends_on': [], 'queue': 'render'}
            ]
        },
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot=bp.graph,
        topic='test',
    )
    parent = StageExecution.objects.create(
        run=run,
        stage_key='motion',
        status=StageStatus.SUCCEEDED,
        output={'shards': [{'shard_index': 0, 'status': 'SUCCEEDED'}]},
    )
    for i, scene_idx in enumerate([0, 1]):
        StageExecution.objects.create(
            run=run,
            stage_key='motion',
            parent=parent,
            shard_index=i,
            status=StageStatus.SUCCEEDED,
            output={'scene_idx': scene_idx, 'asset_id': f'vid-{scene_idx}'},
        )

    ctx = MagicMock()
    ctx.run = run

    result = _run_async(_build_scene_asset_map(ctx))
    assert result == {0: 'vid-0', 1: 'vid-1'}


@pytest.mark.django_db(transaction=True)
def test_build_chapter_audio_map_queries_tts_children() -> None:
    """_build_chapter_audio_map reads chapter_idx+asset_id from tts children."""
    channel = Channel.objects.create(
        name='Asm DB Ch2', kind=ChannelKind.LONGFORM
    )
    bp = PipelineBlueprint.objects.create(
        name='asm_db_v2',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {'key': 'assembly', 'depends_on': [], 'queue': 'render'}
            ]
        },
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot=bp.graph,
        topic='test',
    )
    parent = StageExecution.objects.create(
        run=run,
        stage_key='tts',
        status=StageStatus.SUCCEEDED,
        output={'shards': [{'shard_index': 0, 'status': 'SUCCEEDED'}]},
    )
    StageExecution.objects.create(
        run=run,
        stage_key='tts',
        parent=parent,
        shard_index=0,
        status=StageStatus.SUCCEEDED,
        output={'chapter_idx': 0, 'asset_id': 'audio-ch0', 'char_count': 100},
    )

    ctx = MagicMock()
    ctx.run = run

    result = _run_async(_build_chapter_audio_map(ctx))
    assert result == {0: 'audio-ch0'}
