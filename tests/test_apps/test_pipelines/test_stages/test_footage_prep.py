"""Tests for the footage_prep fan-out stage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.footage_prep import (
    FootagePrepStage,
    _load_asset_bytes,
)


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.id = 'run-uuid'
    ctx.upstream = {
        'footage_search': {
            'shards': [
                {'scene_idx': 0, 'asset_id': 'a0', 'media_type': 'video'},
                {'scene_idx': 1, 'asset_id': 'a1', 'media_type': 'image'},
            ],
        },
        'scene_breakdown': {
            'scenes': [
                {'idx': 0, 'est_seconds': 8.0},
                {'idx': 1, 'est_seconds': 6.0},
            ],
        },
    }
    ctx.config = {}
    ctx.costs = AsyncMock()
    ctx.assets = AsyncMock()
    ctx.assets.save = AsyncMock(return_value=MagicMock(id='seg-uuid'))
    return ctx


def test_load_asset_bytes_reads_from_storage() -> None:
    """_load_asset_bytes awaits the ORM lookup then reads the file field.

    Mocks at the ORM boundary (Asset.objects.aget) rather than patching the
    whole helper, so the real asyncio.to_thread(file.read) call is exercised.
    """
    fake_asset = MagicMock()
    fake_asset.file.read.return_value = b'raw-bytes'
    with patch(
        'server.apps.assets.models.Asset.objects.aget',
        new=AsyncMock(return_value=fake_asset),
    ):
        result = asyncio.run(_load_asset_bytes('some-id'))
    assert result == b'raw-bytes'


def test_stage_key_and_queue() -> None:
    """The stage runs on the render queue."""
    assert FootagePrepStage.key == 'footage_prep'
    assert FootagePrepStage.queue == 'render'


def test_fan_out_carries_media_type_and_duration() -> None:
    """Each shard knows its media type and target duration."""
    shards = FootagePrepStage().fan_out(_make_ctx())
    assert shards is not None
    assert shards[0] == {
        'scene_idx': 0,
        'asset_id': 'a0',
        'media_type': 'video',
        'est_seconds': 8.0,
    }
    assert shards[1]['media_type'] == 'image'


def test_video_shard_normalizes_the_clip() -> None:
    """A video shard runs normalize_clip and reports its method."""
    ctx = _make_ctx()
    ctx.execution.input_snapshot = {
        'scene_idx': 0,
        'asset_id': 'a0',
        'media_type': 'video',
        'est_seconds': 8.0,
    }
    with (
        patch(
            'server.apps.pipelines.stages.footage_prep._load_asset_bytes',
            new=AsyncMock(return_value=b'src'),
        ),
        patch(
            'server.apps.rendering.ffmpeg.normalize_clip',
            new=AsyncMock(return_value=(b'out', 'clip_trim')),
        ),
    ):
        result = asyncio.run(FootagePrepStage().run(ctx))
    assert result == {
        'scene_idx': 0,
        'asset_id': 'seg-uuid',
        'duration_s': 8.0,
        'method': 'clip_trim',
    }


def test_image_shard_applies_ken_burns() -> None:
    """An image shard reuses the shared Ken Burns helper."""
    ctx = _make_ctx()
    ctx.execution.input_snapshot = {
        'scene_idx': 1,
        'asset_id': 'a1',
        'media_type': 'image',
        'est_seconds': 6.0,
    }
    with (
        patch(
            'server.apps.pipelines.stages.footage_prep._load_asset_bytes',
            new=AsyncMock(return_value=b'img'),
        ),
        patch(
            'server.apps.rendering.ffmpeg.ken_burns',
            new=AsyncMock(return_value=b'out'),
        ),
    ):
        result = asyncio.run(FootagePrepStage().run(ctx))
    assert result['method'] == 'ken_burns'
    assert result['duration_s'] == 6.0


def test_output_shape_matches_motion_stage() -> None:
    """Assembly reads these keys; they must match motion exactly."""
    ctx = _make_ctx()
    ctx.execution.input_snapshot = {
        'scene_idx': 0,
        'asset_id': 'a0',
        'media_type': 'video',
        'est_seconds': 8.0,
    }
    with (
        patch(
            'server.apps.pipelines.stages.footage_prep._load_asset_bytes',
            new=AsyncMock(return_value=b'src'),
        ),
        patch(
            'server.apps.rendering.ffmpeg.normalize_clip',
            new=AsyncMock(return_value=(b'out', 'clip_trim')),
        ),
    ):
        result = asyncio.run(FootagePrepStage().run(ctx))
    assert set(result) == {'scene_idx', 'asset_id', 'duration_s', 'method'}
