"""Tests for the assembly pipeline stage."""

import asyncio
from pathlib import Path
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
    _build_chapter_files,
    _build_music_map,
    _build_music_paths,
    _build_scene_asset_map,
    _fetch_asset_bytes,
    _fetch_library_bytes,
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


def test_build_chapter_files_converts_absolute_times_to_chapter_relative(
    tmp_path: Path,
) -> None:
    """Alignment start_s/end_s are absolute; mux atrim must be TTS-relative.

    Regression: chapter 1+ absolute windows past the chapter MP3 length
    produced video-only mezzanines (empty atrim).
    """
    scene_groups = {
        0: [
            {
                'chapter_idx': 0,
                'segment_idx': 0,
                'scene_idx': 0,
                'start_s': 0.1,
                'end_s': 10.0,
            },
        ],
        1: [
            {
                'chapter_idx': 1,
                'segment_idx': 0,
                'scene_idx': 5,
                'start_s': 100.0,
                'end_s': 110.0,
            },
        ],
    }
    (tmp_path / 'ch_000.mp3').write_bytes(b'a')
    (tmp_path / 'ch_001.mp3').write_bytes(b'b')
    chapter_audio_files = {
        0: str(tmp_path / 'ch_000.mp3'),
        1: str(tmp_path / 'ch_001.mp3'),
    }
    mux_calls: list[dict[str, object]] = []

    async def capture_mux(**kwargs: object) -> None:
        mux_calls.append(dict(kwargs))

    async def _inner() -> None:
        with (
            patch(
                'server.apps.pipelines.stages.assembly._fetch_asset_bytes',
                new=AsyncMock(return_value=b'vid'),
            ),
            patch(
                'server.apps.rendering.ffmpeg.mux_scene',
                new=AsyncMock(side_effect=capture_mux),
            ),
            patch(
                'server.apps.rendering.ffmpeg.concat_chapter_with_transition',
                new=AsyncMock(),
            ),
        ):
            await _build_chapter_files(
                tmp_path,
                scene_groups,
                {0: 'vid-0', 5: 'vid-5'},
                chapter_audio_files,
                [],
                chapter_origins={0: 0.0, 1: 100.0},
            )

    asyncio.run(_inner())
    assert len(mux_calls) == 2
    by_out = {str(c['out_path']): c for c in mux_calls}
    ch0 = by_out[str(tmp_path / 'mezz_0000.mp4')]
    ch1 = by_out[str(tmp_path / 'mezz_0005.mp4')]
    assert ch0['start_s'] == pytest.approx(0.1)
    assert ch0['end_s'] == pytest.approx(10.0)
    assert ch1['start_s'] == pytest.approx(0.0)
    assert ch1['end_s'] == pytest.approx(10.0)


def test_build_music_map() -> None:
    entries = [
        {'chapter_idx': 0, 'library_asset_id': 'uuid-a', 'gain_db': -3.0},
        {'chapter_idx': 1, 'library_asset_id': 'uuid-b', 'gain_db': -6.0},
    ]
    result = _build_music_map(entries)
    assert result[0]['library_asset_id'] == 'uuid-a'
    assert result[1]['gain_db'] == -6.0


def test_build_music_paths_downloads_each_chapter_track(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A resolvable library_asset_id downloads and is included in the output."""
    scene_groups = {0: [], 1: []}
    music_map = {
        0: {'library_asset_id': 'uuid-a', 'gain_db': -3.0},
        1: {'library_asset_id': 'uuid-b', 'gain_db': -6.0},
    }

    async def _inner() -> tuple[list[str], list[float]]:
        with patch(
            'server.apps.pipelines.stages.assembly._fetch_library_bytes',
            new=AsyncMock(return_value=b'music bytes'),
        ):
            return await _build_music_paths(tmp_path, scene_groups, music_map)

    paths, gains = asyncio.run(_inner())
    assert len(paths) == 2
    assert gains == [-18.0, -18.0]


def test_build_music_paths_uses_channel_bed_gain(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Channel music_bed_gain_db overrides legacy music_plan gain_db=0."""
    scene_groups = {0: []}
    music_map = {0: {'library_asset_id': 'uuid-a', 'gain_db': 0.0}}

    async def _inner() -> tuple[list[str], list[float]]:
        with patch(
            'server.apps.pipelines.stages.assembly._fetch_library_bytes',
            new=AsyncMock(return_value=b'music bytes'),
        ):
            return await _build_music_paths(
                tmp_path,
                scene_groups,
                music_map,
                channel_bed_gain_db=-20.0,
            )

    _, gains = asyncio.run(_inner())
    assert gains == [-20.0]


def test_build_music_paths_skips_chapter_with_missing_asset(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A library_asset_id with no matching row is skipped, not a crash."""
    from django.core.exceptions import ObjectDoesNotExist

    scene_groups = {0: [], 1: []}
    music_map = {
        0: {'library_asset_id': 'hallucinated-id', 'gain_db': -3.0},
        1: {'library_asset_id': 'uuid-b', 'gain_db': -6.0},
    }

    async def _inner() -> tuple[list[str], list[float]]:
        with patch(
            'server.apps.pipelines.stages.assembly._fetch_library_bytes',
            new=AsyncMock(
                side_effect=[ObjectDoesNotExist(), b'music bytes'],
            ),
        ):
            return await _build_music_paths(tmp_path, scene_groups, music_map)

    paths, gains = asyncio.run(_inner())
    assert len(paths) == 1
    assert gains == [-18.0]


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
                },
            ],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.assets = AsyncMock()
    ctx.assets.save = AsyncMock(return_value=MagicMock(id='final-uuid'))
    ctx.channel.branding = None
    ctx.channel.assembly_style_transition_styles = []
    ctx.channel.assembly_style_sfx_pool_tags = []
    return ctx


def test_pick_transition_style_cycles_by_chapter_index() -> None:
    from server.apps.pipelines.stages.assembly import _pick_transition_style

    pool = ['hard_cut', 'cross_dissolve']
    assert _pick_transition_style(pool, chapter_idx=0) == 'hard_cut'
    assert _pick_transition_style(pool, chapter_idx=1) == 'cross_dissolve'
    assert _pick_transition_style(pool, chapter_idx=2) == 'hard_cut'


def test_pick_transition_style_empty_pool_returns_hard_cut() -> None:
    from server.apps.pipelines.stages.assembly import _pick_transition_style

    assert _pick_transition_style([], chapter_idx=0) == 'hard_cut'


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


def test_assembly_run_calls_final_pass_with_watermark_when_branding_set() -> (
    None
):
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
    from typing import Any

    from asgiref.sync import sync_to_async

    @sync_to_async
    def _close() -> None:
        from django.db import connections

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
        name='Asm DB Ch',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='asm_db_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {'key': 'assembly', 'depends_on': [], 'queue': 'render'},
            ],
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
        name='Asm DB Ch2',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='asm_db_v2',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {'key': 'assembly', 'depends_on': [], 'queue': 'render'},
            ],
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


# ---------------------------------------------------------------------------
# _fetch_asset_bytes / _fetch_library_bytes
# ---------------------------------------------------------------------------


def test_fetch_asset_bytes_reads_file() -> None:
    """_fetch_asset_bytes returns bytes from asset.file.read via to_thread."""
    fake_asset = MagicMock()

    async def _run() -> bytes:
        with (
            patch(
                'server.apps.assets.models.Asset.objects.aget',
                new=AsyncMock(return_value=fake_asset),
            ),
            patch(
                'asyncio.to_thread',
                new=AsyncMock(return_value=b'video-bytes'),
            ),
        ):
            return await _fetch_asset_bytes('asset-uuid')

    result = asyncio.run(_run())
    assert result == b'video-bytes'


def test_fetch_library_bytes_reads_file() -> None:
    """_fetch_library_bytes returns bytes from LibraryAsset via to_thread."""
    fake_asset = MagicMock()

    async def _run() -> bytes:
        with (
            patch(
                'server.apps.assets.models.LibraryAsset.objects.aget',
                new=AsyncMock(return_value=fake_asset),
            ),
            patch(
                'asyncio.to_thread',
                new=AsyncMock(return_value=b'library-bytes'),
            ),
        ):
            return await _fetch_library_bytes('lib-uuid')

    result = asyncio.run(_run())
    assert result == b'library-bytes'


@pytest.mark.django_db(transaction=True)
def test_build_sfx_paths_downloads_matching_sfx(tmp_path: object) -> None:
    """_build_sfx_paths fetches active SFX assets overlapping channel tags."""
    from pathlib import Path

    from server.apps.assets.models import LibraryAsset, LibraryAssetKind
    from server.apps.pipelines.stages.assembly import _build_sfx_paths

    LibraryAsset.objects.create(
        kind=LibraryAssetKind.SFX,
        name='whoosh',
        tags=['whoosh', 'impact'],
        file='library/whoosh.mp3',
    )
    ctx = MagicMock()
    ctx.channel.assembly_style_sfx_pool_tags = ['whoosh']

    async def _inner() -> tuple[list[str], list[float]]:
        with (
            patch(
                'server.apps.pipelines.stages.assembly._fetch_library_bytes',
                new=AsyncMock(return_value=b'sfx-bytes'),
            ),
            patch('asyncio.to_thread', new=AsyncMock()),
        ):
            return await _build_sfx_paths(Path(str(tmp_path)), ctx)

    paths, gains = _run_async(_inner())  # type: ignore[misc]
    assert len(paths) == 1
    assert gains == [-12.0]


def test_build_sfx_paths_empty_tags_returns_empty() -> None:
    """No sfx_pool_tags → no SFX tracks fetched."""
    from pathlib import Path

    from server.apps.pipelines.stages.assembly import _build_sfx_paths

    ctx = MagicMock()
    ctx.channel.assembly_style_sfx_pool_tags = []

    async def _inner() -> tuple[list[str], list[float]]:
        return await _build_sfx_paths(Path('/tmp'), ctx)

    paths, gains = asyncio.run(_inner())
    assert paths == []
    assert gains == []


# ---------------------------------------------------------------------------
# _build_scene_asset_map / _build_chapter_audio_map — missing output fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_build_scene_asset_map_skips_child_with_missing_fields() -> None:
    """Children missing scene_idx or asset_id are ignored (branch 50->41)."""
    channel = Channel.objects.create(
        name='Asm Skip Ch',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='asm_skip_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {'key': 'assembly', 'depends_on': [], 'queue': 'render'},
            ],
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
        output={},
    )
    # Child with no asset_id — should be skipped
    StageExecution.objects.create(
        run=run,
        stage_key='motion',
        parent=parent,
        shard_index=0,
        status=StageStatus.SUCCEEDED,
        output={'scene_idx': 0},  # no asset_id
    )
    # Child with no scene_idx — should also be skipped
    StageExecution.objects.create(
        run=run,
        stage_key='motion',
        parent=parent,
        shard_index=1,
        status=StageStatus.SUCCEEDED,
        output={'asset_id': 'vid-0'},  # no scene_idx
    )

    ctx = MagicMock()
    ctx.run = run

    result = _run_async(_build_scene_asset_map(ctx))
    assert result == {}


@pytest.mark.django_db(transaction=True)
def test_build_chapter_audio_map_skips_child_with_missing_fields() -> None:
    """Children missing asset_id are ignored; chapter_idx falls back to shard_index."""
    channel = Channel.objects.create(
        name='Asm Skip Ch2',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='asm_skip_v2',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {'key': 'assembly', 'depends_on': [], 'queue': 'render'},
            ],
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
        output={},
    )
    # Child with no asset_id
    StageExecution.objects.create(
        run=run,
        stage_key='tts',
        parent=parent,
        shard_index=0,
        status=StageStatus.SUCCEEDED,
        output={'chapter_idx': 0},  # no asset_id
    )
    # Child with no chapter_idx
    StageExecution.objects.create(
        run=run,
        stage_key='tts',
        parent=parent,
        shard_index=1,
        status=StageStatus.SUCCEEDED,
        output={'asset_id': 'audio-0'},  # no chapter_idx
    )

    ctx = MagicMock()
    ctx.run = run

    result = _run_async(_build_chapter_audio_map(ctx))
    assert result == {1: 'audio-0'}


# ---------------------------------------------------------------------------
# AssemblyStage.run — uncovered branches
# ---------------------------------------------------------------------------


def test_assembly_run_with_branding_but_no_watermark() -> None:
    """Branch 123->125: branding exists but watermark attribute is None."""
    ctx = _make_ctx()
    branding = MagicMock()
    branding.watermark = None  # watermark attribute is falsy
    branding.watermark_opacity = 0.5
    ctx.channel.branding = branding
    fake_probe = {'format': {'duration': '5.0'}, 'streams': []}

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


def test_assembly_run_without_ass_and_no_music_for_chapter() -> None:
    """No ass_asset_id (branch 123->125), no music entry (branch 187->185)."""
    ctx = _make_ctx()
    ctx.upstream['alignment']['ass_asset_id'] = None  # no captions
    ctx.upstream['music_plan']['entries'] = []  # no music entries
    fake_probe = {'format': {'duration': '5.0'}, 'streams': []}

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


def test_assembly_run_fails_when_motion_asset_missing() -> None:
    """Missing motion assets fail loudly instead of empty-concat FFmpeg errors."""
    ctx = _make_ctx()

    async def _run() -> dict:  # type: ignore[type-arg]
        with (
            patch(
                'server.apps.pipelines.stages.assembly._build_scene_asset_map',
                new=AsyncMock(return_value={}),
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
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(
                    return_value={
                        'format': {'duration': '10.0'},
                        'streams': [],
                    },
                ),
            ),
        ):
            return await AssemblyStage().run(ctx)

    with pytest.raises(ValueError, match='missing motion assets'):
        asyncio.run(_run())


def test_assembly_run_fails_when_scene_idx_missing() -> None:
    """Alignment rows without scene_idx are rejected before mux."""
    ctx = _make_ctx()
    del ctx.upstream['alignment']['scenes'][0]['scene_idx']

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
                'server.apps.rendering.ffmpeg.async_ffprobe',
                new=AsyncMock(
                    return_value={
                        'format': {'duration': '10.0'},
                        'streams': [],
                    },
                ),
            ),
        ):
            return await AssemblyStage().run(ctx)

    with pytest.raises(ValueError, match='missing scene_idx'):
        asyncio.run(_run())


def test_build_scene_asset_map_defaults_to_motion() -> None:
    """A blueprint with no profile still reads motion shard outputs."""
    from unittest.mock import MagicMock

    from server.apps.pipelines.stages.assembly import _resolve_segment_stage

    ctx = MagicMock()
    ctx.run.blueprint_snapshot = {'stages': []}
    assert _resolve_segment_stage(ctx) == 'motion'


def test_build_scene_asset_map_uses_documentary_segment_stage() -> None:
    """A documentary blueprint reads footage_prep shard outputs instead."""
    from unittest.mock import MagicMock

    from server.apps.pipelines.stages.assembly import _resolve_segment_stage

    ctx = MagicMock()
    ctx.run.blueprint_snapshot = {
        'stages': [],
        'profile': 'documentary_footage',
    }
    assert _resolve_segment_stage(ctx) == 'footage_prep'


@pytest.mark.django_db(transaction=True)
def test_build_scene_asset_map_queries_footage_prep_children() -> None:
    """Documentary blueprints read scene_idx+asset_id from footage_prep."""
    channel = Channel.objects.create(
        name='Asm Doc Ch',
        kind=ChannelKind.LONGFORM,
    )
    bp = PipelineBlueprint.objects.create(
        name='asm_doc_v1',
        kind=PipelineKind.LONGFORM,
        graph={
            'stages': [
                {'key': 'assembly', 'depends_on': [], 'queue': 'render'},
            ],
            'profile': 'documentary_footage',
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
        stage_key='footage_prep',
        status=StageStatus.SUCCEEDED,
        output={'shards': [{'shard_index': 0, 'status': 'SUCCEEDED'}]},
    )
    for i, scene_idx in enumerate([0, 1]):
        StageExecution.objects.create(
            run=run,
            stage_key='footage_prep',
            parent=parent,
            shard_index=i,
            status=StageStatus.SUCCEEDED,
            output={'scene_idx': scene_idx, 'asset_id': f'fp-{scene_idx}'},
        )
    # A motion child with the same run must NOT leak into the result —
    # proves the filter discriminates by stage_key, not just parent/run.
    motion_parent = StageExecution.objects.create(
        run=run,
        stage_key='motion',
        status=StageStatus.SUCCEEDED,
        output={'shards': [{'shard_index': 0, 'status': 'SUCCEEDED'}]},
    )
    StageExecution.objects.create(
        run=run,
        stage_key='motion',
        parent=motion_parent,
        shard_index=0,
        status=StageStatus.SUCCEEDED,
        output={'scene_idx': 0, 'asset_id': 'vid-0'},
    )

    ctx = MagicMock()
    ctx.run = run

    result = _run_async(_build_scene_asset_map(ctx))
    assert result == {0: 'fp-0', 1: 'fp-1'}
