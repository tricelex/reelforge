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
    ctx.prompts.get_model = AsyncMock(return_value=None)
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
                'httpx.AsyncClient.get',
                new=AsyncMock(return_value=mock_resp),
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


def test_image_gen_uses_library_asset_character_ref_url() -> None:
    """character_ref_id is a LibraryAsset id; pass its file URL to fal."""
    import httpx

    from server.apps.assets.models import LibraryAsset

    ctx = _make_ctx()
    ctx.config = {'model': 'fal-ai/flux/dev', 'use_character_ref': True}
    ctx.execution.shard_index = 0
    ctx.execution.parent_id = 'p'
    ref_id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
    ctx.execution.input_snapshot = {
        'scene_idx': 0,
        'prompt': 'Hero walks',
        'negative_prompt': '',
        'safety_flagged': False,
        'character_ref_id': ref_id,
    }

    lib_asset = MagicMock()
    lib_asset.file.url = 'https://cdn.example/hero-ref.jpg'
    fal_mock = AsyncMock(
        return_value={
            'url': 'https://fal.ai/out.jpg',
            'seed': 7,
            'content_policy_violation': False,
        },
    )
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.content = b'jpg'

    async def _inner() -> dict[str, object]:
        with (
            patch.object(
                LibraryAsset.objects,
                'aget',
                new=AsyncMock(return_value=lib_asset),
            ) as lib_aget,
            patch(
                'server.apps.generation.clients.fal.generate_image',
                new=fal_mock,
            ),
            patch(
                'httpx.AsyncClient.get',
                new=AsyncMock(return_value=mock_resp),
            ),
        ):
            result = await ImageGenStage().run(ctx)
            lib_aget.assert_awaited_once_with(id=str(ref_id))
            return result

    result = asyncio.run(_inner())
    assert result['scene_idx'] == 0
    assert fal_mock.await_args.kwargs['model'] == 'fal-ai/flux-pro/kontext'
    assert fal_mock.await_args.kwargs['image_url'] == (
        'https://cdn.example/hero-ref.jpg'
    )
    assert fal_mock.await_args.kwargs['image_urls'] is None


def test_image_gen_missing_library_ref_continues_without_url() -> None:
    """Missing LibraryAsset skips the ref instead of failing the shard."""
    import httpx

    from server.apps.assets.models import LibraryAsset

    ctx = _make_ctx()
    ctx.config = {'model': 'fal-ai/flux/dev', 'use_character_ref': True}
    ctx.execution.shard_index = 0
    ctx.execution.parent_id = 'p'
    ctx.execution.input_snapshot = {
        'scene_idx': 0,
        'prompt': 'Hero walks',
        'negative_prompt': '',
        'safety_flagged': False,
        'character_ref_id': 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    }

    fal_mock = AsyncMock(
        return_value={
            'url': 'https://fal.ai/out.jpg',
            'seed': 9,
            'content_policy_violation': False,
        },
    )
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.content = b'jpg'

    async def _inner() -> None:
        with (
            patch.object(
                LibraryAsset.objects,
                'aget',
                new=AsyncMock(side_effect=LibraryAsset.DoesNotExist),
            ),
            patch(
                'server.apps.generation.clients.fal.generate_image',
                new=fal_mock,
            ),
            patch(
                'httpx.AsyncClient.get',
                new=AsyncMock(return_value=mock_resp),
            ),
        ):
            await ImageGenStage().run(ctx)

    asyncio.run(_inner())
    assert fal_mock.await_args is not None
    assert fal_mock.await_args.kwargs['image_url'] is None


def test_image_gen_setting_anchor_routes_to_kontext() -> None:
    """A setting establishing shot is passed to Flux Kontext, not flux/dev."""
    import httpx

    ctx = _make_ctx(n_scenes=1)
    ctx.config = {'model': 'fal-ai/flux/dev', 'use_character_ref': True}
    ctx.execution.shard_index = 0
    ctx.execution.parent_id = 'p'
    ctx.execution.input_snapshot = {
        'scene_idx': 0,
        'prompt': 'Forum close-up',
        'negative_prompt': 'cars',
        'safety_flagged': False,
        'character_ref_id': None,
        'setting_anchor_url': 'https://cdn.example/forum.jpg',
    }
    fal_mock = AsyncMock(
        return_value={
            'url': 'https://fal.ai/out.jpg',
            'seed': 3,
            'content_policy_violation': False,
        },
    )
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.content = b'jpg'

    async def _inner() -> None:
        with (
            patch(
                'server.apps.generation.clients.fal.generate_image',
                new=fal_mock,
            ),
            patch(
                'httpx.AsyncClient.get',
                new=AsyncMock(return_value=mock_resp),
            ),
        ):
            await ImageGenStage().run(ctx)

    asyncio.run(_inner())
    assert fal_mock.await_args is not None
    assert fal_mock.await_args.kwargs['model'] == 'fal-ai/flux-pro/kontext'
    assert fal_mock.await_args.kwargs['image_url'] == (
        'https://cdn.example/forum.jpg'
    )
    assert 'Keep identity' in fal_mock.await_args.kwargs['prompt']


def test_image_gen_fan_out_attaches_setting_anchor_url() -> None:
    """Shards carry the establishing-shot URL for the scene setting."""
    ctx = _make_ctx(n_scenes=1)
    ctx.upstream['scene_breakdown'] = {
        'scenes': [{'idx': 0, 'setting': 'Roman forum'}],
    }
    ctx.upstream['visual_anchors'] = {
        'anchors': [
            {
                'setting': 'roman forum',
                'url': 'https://cdn.example/forum.jpg',
            },
        ],
    }
    shards = ImageGenStage().fan_out(ctx)
    assert shards is not None
    assert shards[0]['setting_anchor_url'] == 'https://cdn.example/forum.jpg'


def test_image_gen_character_and_setting_use_kontext_multi() -> None:
    """Hero sheet plus establishing shot hit the multi-ref endpoint."""
    import httpx

    from server.apps.assets.models import LibraryAsset

    ctx = _make_ctx(n_scenes=1)
    ctx.config = {'model': 'fal-ai/flux/dev', 'use_character_ref': True}
    ctx.execution.shard_index = 0
    ctx.execution.parent_id = 'p'
    ref_id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
    ctx.execution.input_snapshot = {
        'scene_idx': 0,
        'prompt': 'Hero in the forum',
        'negative_prompt': '',
        'safety_flagged': False,
        'character_ref_id': ref_id,
        'setting_anchor_url': 'https://cdn.example/forum.jpg',
    }
    lib_asset = MagicMock()
    lib_asset.file.url = 'https://cdn.example/hero-ref.jpg'
    fal_mock = AsyncMock(
        return_value={
            'url': 'https://fal.ai/out.jpg',
            'seed': 4,
            'content_policy_violation': False,
        },
    )
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.content = b'jpg'

    async def _inner() -> None:
        with (
            patch.object(
                LibraryAsset.objects,
                'aget',
                new=AsyncMock(return_value=lib_asset),
            ),
            patch(
                'server.apps.generation.clients.fal.generate_image',
                new=fal_mock,
            ),
            patch(
                'httpx.AsyncClient.get',
                new=AsyncMock(return_value=mock_resp),
            ),
        ):
            await ImageGenStage().run(ctx)

    asyncio.run(_inner())
    assert fal_mock.await_args is not None
    assert fal_mock.await_args.kwargs['model'] == (
        'fal-ai/flux-pro/kontext/multi'
    )
    assert fal_mock.await_args.kwargs['image_urls'] == [
        'https://cdn.example/hero-ref.jpg',
        'https://cdn.example/forum.jpg',
    ]


def test_image_gen_empty_library_file_skips_character_url() -> None:
    """A LibraryAsset with no file is treated as a missing character ref."""
    import httpx

    from server.apps.assets.models import LibraryAsset

    ctx = _make_ctx()
    ctx.config = {'model': 'fal-ai/flux/dev', 'use_character_ref': True}
    ctx.execution.shard_index = 0
    ctx.execution.parent_id = 'p'
    ctx.execution.input_snapshot = {
        'scene_idx': 0,
        'prompt': 'Hero walks',
        'negative_prompt': '',
        'safety_flagged': False,
        'character_ref_id': 'cccccccc-cccc-cccc-cccc-cccccccccccc',
    }
    lib_asset = MagicMock()
    lib_asset.file = None
    fal_mock = AsyncMock(
        return_value={
            'url': 'https://fal.ai/out.jpg',
            'seed': 8,
            'content_policy_violation': False,
        },
    )
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.content = b'jpg'

    async def _inner() -> None:
        with (
            patch.object(
                LibraryAsset.objects,
                'aget',
                new=AsyncMock(return_value=lib_asset),
            ),
            patch(
                'server.apps.generation.clients.fal.generate_image',
                new=fal_mock,
            ),
            patch(
                'httpx.AsyncClient.get',
                new=AsyncMock(return_value=mock_resp),
            ),
        ):
            await ImageGenStage().run(ctx)

    asyncio.run(_inner())
    assert fal_mock.await_args is not None
    assert fal_mock.await_args.kwargs['image_url'] is None
    assert fal_mock.await_args.kwargs['model'] == 'fal-ai/flux/dev'


def test_image_gen_fan_out_skips_blank_anchor_urls() -> None:
    """Empty setting keys and blank URLs are not attached to shards."""
    ctx = _make_ctx(n_scenes=2)
    ctx.upstream['scene_breakdown'] = {
        'scenes': [
            {'setting': 'Roman forum'},
            {'idx': 0, 'setting': ''},
            {'idx': 1, 'setting': 'Harbor'},
        ],
    }
    ctx.upstream['visual_anchors'] = {
        'anchors': [
            {'setting': '', 'url': 'https://cdn.example/ignored.jpg'},
            {'setting': 'harbor', 'url': ''},
        ],
    }
    shards = ImageGenStage().fan_out(ctx)
    assert shards is not None
    assert shards[0]['setting_anchor_url'] is None
    assert shards[1]['setting_anchor_url'] is None


def test_image_gen_ignores_character_ref_when_flag_off() -> None:
    """use_character_ref false never looks up the hero sheet."""
    import httpx

    from server.apps.assets.models import LibraryAsset

    ctx = _make_ctx()
    ctx.config = {'model': 'fal-ai/flux/dev', 'use_character_ref': False}
    ctx.execution.shard_index = 0
    ctx.execution.parent_id = 'p'
    ctx.execution.input_snapshot = {
        'scene_idx': 0,
        'prompt': 'Hero walks',
        'negative_prompt': '',
        'safety_flagged': False,
        'character_ref_id': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        'setting_anchor_url': 'https://cdn.example/forum.jpg',
    }
    fal_mock = AsyncMock(
        return_value={
            'url': 'https://fal.ai/out.jpg',
            'seed': 1,
            'content_policy_violation': False,
        },
    )
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.content = b'jpg'
    lib_aget = AsyncMock()

    async def _inner() -> None:
        with (
            patch.object(LibraryAsset.objects, 'aget', new=lib_aget),
            patch(
                'server.apps.generation.clients.fal.generate_image',
                new=fal_mock,
            ),
            patch(
                'httpx.AsyncClient.get',
                new=AsyncMock(return_value=mock_resp),
            ),
        ):
            await ImageGenStage().run(ctx)

    asyncio.run(_inner())
    lib_aget.assert_not_awaited()
    assert fal_mock.await_args is not None
    assert fal_mock.await_args.kwargs['model'] == 'fal-ai/flux-pro/kontext'
    assert fal_mock.await_args.kwargs['image_url'] == (
        'https://cdn.example/forum.jpg'
    )


def test_image_gen_merges_channel_style_negatives() -> None:
    """Niche style_negatives are merged into the fal negative_prompt."""
    import httpx

    ctx = _make_ctx(n_scenes=1)
    niche = MagicMock()
    niche.visual_bible = 'flat-color 2D'
    niche.lore_document = ''
    niche.angle = ''
    niche.visual_medium = '2d_animation'
    niche.style_negatives = ['photorealistic', 'live action']
    ctx.channel.niche_config = niche
    ctx.execution.shard_index = 0
    ctx.execution.parent_id = 'p'
    ctx.execution.input_snapshot = {
        'scene_idx': 0,
        'prompt': 'Harbor still',
        'negative_prompt': 'cars',
        'safety_flagged': False,
        'character_ref_id': None,
        'setting_anchor_url': None,
    }
    fal_mock = AsyncMock(
        return_value={
            'url': 'https://fal.ai/out.jpg',
            'seed': 1,
            'content_policy_violation': False,
        },
    )
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.content = b'jpg'

    async def _inner() -> None:
        with (
            patch(
                'server.apps.generation.clients.fal.generate_image',
                new=fal_mock,
            ),
            patch(
                'httpx.AsyncClient.get',
                new=AsyncMock(return_value=mock_resp),
            ),
        ):
            await ImageGenStage().run(ctx)

    asyncio.run(_inner())
    assert fal_mock.await_args is not None
    negative = fal_mock.await_args.kwargs['negative_prompt']
    assert 'cars' in negative
    assert 'photorealistic' in negative
    assert 'live action' in negative
