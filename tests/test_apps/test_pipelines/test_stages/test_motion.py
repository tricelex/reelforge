"""Tests for the motion fan-out stage (Kling I2V + Ken Burns)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.motion import MotionStage


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.prompt_snapshot = {}
    ctx.execution.shard_index = None
    ctx.execution.parent_id = None
    ctx.upstream = {
        'image_gen': {
            'shards': [
                {
                    'shard_index': 0,
                    'scene_idx': 0,
                    'asset_id': 'img-0',
                    'seed': 1,
                },
                {
                    'shard_index': 1,
                    'scene_idx': 1,
                    'asset_id': 'img-1',
                    'seed': 2,
                },
            ],
        },
        'scene_breakdown': {
            'scenes': [
                {
                    'idx': 0,
                    'is_hero': True,
                    'est_seconds': 8.0,
                    'visual_concept': 'aerial shot',
                },
                {
                    'idx': 1,
                    'is_hero': False,
                    'est_seconds': 7.0,
                    'visual_concept': 'map pan',
                },
            ],
        },
    }
    ctx.config = {
        'i2v_model': 'fal-ai/kling-video/v2.1/standard/image-to-video',
    }
    ctx.costs = AsyncMock()
    ctx.assets = AsyncMock()
    ctx.assets.save = AsyncMock(return_value=MagicMock(id='video-uuid'))
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    return ctx


def test_motion_stage_key() -> None:
    """MotionStage has the expected class attributes."""
    assert MotionStage.key == 'motion'
    assert MotionStage.queue == 'render'


def test_motion_fan_out_one_per_scene() -> None:
    """fan_out() returns one shard per image_gen result."""
    ctx = _make_ctx()
    shards = MotionStage().fan_out(ctx)
    assert shards is not None
    assert len(shards) == 2
    assert shards[0]['is_hero'] is True
    assert shards[1]['is_hero'] is False


def test_motion_hero_scene_calls_kling() -> None:
    """Hero scenes use Kling I2V and return method='kling'."""
    import httpx

    ctx = _make_ctx()
    ctx.execution.shard_index = 0
    ctx.execution.parent_id = 'parent'
    ctx.execution.input_snapshot = {
        'scene_idx': 0,
        'asset_id': 'img-0',
        'is_hero': True,
        'est_seconds': 8.0,
        'visual_concept': 'aerial shot',
        'image_url': 'https://storage/img-0.jpg',
    }

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.fal.generate_video_kling',
                new=AsyncMock(
                    return_value={
                        'video_url': 'https://fal.ai/vid.mp4',
                        'duration_s': 5,
                    },
                ),
            ),
            patch(
                'httpx.AsyncClient.get',
                new=AsyncMock(
                    return_value=MagicMock(
                        spec=httpx.Response,
                        is_success=True,
                        content=b'fake-video',
                    ),
                ),
            ),
        ):
            return await MotionStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['scene_idx'] == 0
    assert result['method'] == 'kling'
    assert 'asset_id' in result


def test_motion_non_hero_scene_runs_ken_burns() -> None:
    """Non-hero scenes use Ken Burns and return method='ken_burns'."""
    ctx = _make_ctx()
    ctx.execution.shard_index = 1
    ctx.execution.parent_id = 'parent'
    ctx.execution.input_snapshot = {
        'scene_idx': 1,
        'asset_id': 'img-1',
        'is_hero': False,
        'est_seconds': 7.0,
        'visual_concept': 'map pan',
        'image_url': 'https://storage/img-1.jpg',
    }

    async def _inner() -> dict[str, object]:
        with patch(
            'server.apps.pipelines.stages.motion._run_ken_burns',
            new=AsyncMock(return_value=b'fake-ken-burns-video'),
        ):
            return await MotionStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['scene_idx'] == 1
    assert result['method'] == 'ken_burns'
    assert 'asset_id' in result


def test_run_ken_burns_returns_video_bytes() -> None:
    """_run_ken_burns downloads image, runs FFmpeg, returns video bytes."""
    import httpx

    from server.apps.pipelines.stages.motion import (
        _run_ken_burns,
    )

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'', b''))

    async def _inner() -> bytes:
        with (
            patch(
                'httpx.AsyncClient.get',
                new=AsyncMock(
                    return_value=MagicMock(
                        spec=httpx.Response,
                        content=b'fake-image',
                    ),
                ),
            ),
            patch(
                'asyncio.create_subprocess_exec',
                new=AsyncMock(return_value=mock_proc),
            ),
            patch(
                'server.apps.pipelines.stages.motion.Path.read_bytes',
                return_value=b'fake-video',
            ),
        ):
            return await _run_ken_burns('https://storage/img.jpg', 5.0)

    result = asyncio.run(_inner())
    assert result == b'fake-video'


def test_run_ken_burns_raises_on_ffmpeg_failure() -> None:
    """_run_ken_burns raises RuntimeError if FFmpeg exits non-zero."""
    import httpx

    from server.apps.pipelines.stages.motion import (
        _run_ken_burns,
    )

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b'', b'codec not found'))

    async def _inner() -> None:
        with (
            patch(
                'httpx.AsyncClient.get',
                new=AsyncMock(
                    return_value=MagicMock(
                        spec=httpx.Response,
                        content=b'fake-image',
                    ),
                ),
            ),
            patch(
                'asyncio.create_subprocess_exec',
                new=AsyncMock(return_value=mock_proc),
            ),
        ):
            await _run_ken_burns('https://storage/img.jpg', 5.0)

    try:
        asyncio.run(_inner())
        raise AssertionError('expected RuntimeError')
    except RuntimeError as e:
        assert 'FFmpeg Ken Burns failed' in str(e)
