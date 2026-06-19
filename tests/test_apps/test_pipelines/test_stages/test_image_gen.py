"""Tests for the image_gen fan-out stage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.image_gen import ImageGenStage


def _make_ctx(n_scenes: int = 3) -> MagicMock:
    ctx = MagicMock()
    ctx.run.topic = 'Rome'
    ctx.run.prompt_snapshot = {}
    ctx.execution.shard_index = None
    ctx.execution.parent_id = None
    ctx.upstream = {
        'visual_prompts': {
            'prompts': [
                {
                    'scene_idx': i,
                    'prompt': f'Epic scene {i}',
                    'negative_prompt': 'modern',
                    'safety_flagged': False,
                    'character_ref_id': None,
                }
                for i in range(n_scenes)
            ],
        },
    }
    ctx.config = {'model': 'fal-ai/flux/dev', 'use_character_ref': False}
    ctx.costs = AsyncMock()
    ctx.assets = AsyncMock()
    ctx.assets.save = AsyncMock(return_value=MagicMock(id='asset-uuid'))
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    return ctx


def test_image_gen_stage_key() -> None:
    """ImageGenStage has the expected class attributes."""
    assert ImageGenStage.key == 'image_gen'
    assert ImageGenStage.queue == 'api'


def test_image_gen_fan_out_returns_one_dict_per_scene() -> None:
    """fan_out() returns one shard dict per visual prompt."""
    ctx = _make_ctx(n_scenes=5)
    shards = ImageGenStage().fan_out(ctx)
    assert shards is not None
    assert len(shards) == 5
    assert shards[0]['scene_idx'] == 0
    assert shards[4]['scene_idx'] == 4


def test_image_gen_run_child_returns_scene_asset() -> None:
    """A child shard execution calls fal.generate_image and saves asset."""
    import httpx

    ctx = _make_ctx(n_scenes=3)
    ctx.execution.shard_index = 1
    ctx.execution.parent_id = 'some-parent-id'
    ctx.execution.input_snapshot = {
        'scene_idx': 1,
        'prompt': 'Epic scene 1',
        'negative_prompt': 'modern',
        'safety_flagged': False,
        'character_ref_id': None,
    }

    async def _inner() -> dict[str, object]:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.is_success = True
        mock_resp.content = b'fake-png'

        with (
            patch(
                'server.apps.generation.clients.fal.generate_image',
                new=AsyncMock(
                    return_value={
                        'url': 'https://fal.ai/fake.png',
                        'seed': 12345,
                        'content_policy_violation': False,
                    },
                ),
            ),
            patch(
                'httpx.AsyncClient.get', new=AsyncMock(return_value=mock_resp),
            ),
        ):
            return await ImageGenStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['scene_idx'] == 1
    assert 'asset_id' in result
    assert result['seed'] == 12345


def test_image_gen_safety_preflag_raises_fatal() -> None:
    """safety_flagged=True in input_snapshot raises FatalProviderError."""
    from server.common.exceptions import FatalProviderError

    ctx = _make_ctx()
    ctx.execution.shard_index = 0
    ctx.execution.parent_id = 'p'
    ctx.execution.input_snapshot = {
        'scene_idx': 0,
        'prompt': 'bad',
        'negative_prompt': '',
        'safety_flagged': True,
        'character_ref_id': None,
    }

    async def _inner() -> None:
        await ImageGenStage().run(ctx)

    try:
        asyncio.run(_inner())
        raise AssertionError('expected FatalProviderError')
    except FatalProviderError:
        pass


def test_image_gen_content_policy_violation_after_gen_raises_fatal() -> None:
    """When fal returns content_policy_violation=True post-generation, raises FatalProviderError."""
    from server.common.exceptions import FatalProviderError

    ctx = _make_ctx()
    ctx.execution.shard_index = 0
    ctx.execution.parent_id = 'p'
    ctx.execution.input_snapshot = {
        'scene_idx': 0,
        'prompt': 'borderline prompt',
        'negative_prompt': '',
        'safety_flagged': False,
        'character_ref_id': None,
    }

    async def _inner() -> None:
        with patch(
            'server.apps.generation.clients.fal.generate_image',
            new=AsyncMock(
                return_value={
                    'url': 'https://fal.ai/img.jpg',
                    'seed': 1,
                    'content_policy_violation': True,
                },
            ),
        ):
            await ImageGenStage().run(ctx)

    try:
        asyncio.run(_inner())
        raise AssertionError('expected FatalProviderError')
    except FatalProviderError:
        pass
