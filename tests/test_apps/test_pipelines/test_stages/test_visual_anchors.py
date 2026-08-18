"""Tests for the visual_anchors establishing-shot stage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.visual_anchors import VisualAnchorsStage


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.prompt_snapshot = {}
    ctx.channel.niche_config = MagicMock()
    ctx.channel.niche_config.lore_document = 'desaturated documentary'
    ctx.channel.niche_config.angle = ''
    ctx.upstream = {
        'scene_breakdown': {
            'scenes': [
                {'idx': 0, 'setting': 'Roman forum'},
                {'idx': 1, 'setting': 'roman forum'},
                {'idx': 2, 'setting': 'Harbor at dawn'},
            ],
        },
    }
    ctx.config = {'model': 'fal-ai/flux/dev'}
    ctx.costs = AsyncMock()
    ctx.assets = AsyncMock()
    saved = MagicMock()
    saved.id = 'anchor-asset'
    saved.file.url = 'https://cdn.example/anchor.jpg'
    ctx.assets.save = AsyncMock(return_value=saved)
    return ctx


def test_visual_anchors_stage_key() -> None:
    """VisualAnchorsStage is a single-execution api stage."""
    assert VisualAnchorsStage.key == 'visual_anchors'
    assert VisualAnchorsStage.queue == 'api'
    assert VisualAnchorsStage().fan_out(MagicMock()) is None


def test_visual_anchors_generates_one_still_per_unique_setting() -> None:
    """Duplicate settings collapse; each unique setting gets one Flux still."""
    import httpx

    ctx = _make_ctx()
    fal_mock = AsyncMock(
        return_value={
            'url': 'https://fal.ai/est.jpg',
            'seed': 11,
            'content_policy_violation': False,
        },
    )
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.content = b'jpg'

    async def _inner() -> dict[str, object]:
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
            return await VisualAnchorsStage().run(ctx)

    result = asyncio.run(_inner())
    assert fal_mock.await_count == 2
    settings = [row['setting'] for row in result['anchors']]  # type: ignore[index]
    assert settings == ['roman forum', 'harbor at dawn']
    assert result['anchors'][0]['url'] == 'https://cdn.example/anchor.jpg'  # type: ignore[index]
    assert (
        'desaturated documentary'
        in fal_mock.await_args_list[0].kwargs['prompt']
    )


def test_visual_anchors_empty_scenes_returns_no_anchors() -> None:
    """No settings means no establishing shots."""
    ctx = _make_ctx()
    ctx.upstream = {'scene_breakdown': {'scenes': []}}

    result = asyncio.run(VisualAnchorsStage().run(ctx))
    assert result == {'anchors': []}


def test_visual_anchors_falls_back_to_fal_url_when_file_missing() -> None:
    """Saved assets without a file still record the fal result URL."""
    import httpx

    ctx = _make_ctx()
    saved = MagicMock()
    saved.id = 'anchor-asset'
    saved.file = None
    ctx.assets.save = AsyncMock(return_value=saved)
    fal_mock = AsyncMock(
        return_value={
            'url': 'https://fal.ai/est.jpg',
            'seed': 11,
            'content_policy_violation': False,
        },
    )
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.content = b'jpg'

    async def _inner() -> dict[str, object]:
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
            return await VisualAnchorsStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['anchors'][0]['url'] == 'https://fal.ai/est.jpg'  # type: ignore[index]


def test_visual_anchors_missing_niche_still_generates() -> None:
    """ObjectDoesNotExist on niche_config does not skip establishing shots."""
    import httpx
    from django.core.exceptions import ObjectDoesNotExist

    ctx = _make_ctx()
    ctx.upstream['scene_breakdown']['scenes'] = [
        {'idx': 0, 'setting': 'Harbor'},
    ]

    class _NoNiche(MagicMock):
        @property
        def niche_config(self) -> object:
            raise ObjectDoesNotExist

    ctx.channel = _NoNiche()
    fal_mock = AsyncMock(
        return_value={
            'url': 'https://fal.ai/est.jpg',
            'seed': 2,
            'content_policy_violation': False,
        },
    )
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.content = b'jpg'

    async def _inner() -> dict[str, object]:
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
            return await VisualAnchorsStage().run(ctx)

    result = asyncio.run(_inner())
    assert fal_mock.await_count == 1
    assert result['anchors'][0]['setting'] == 'harbor'  # type: ignore[index]


def test_visual_anchors_none_niche_skips_lore() -> None:
    """niche_config=None still generates establishing shots."""
    import httpx

    ctx = _make_ctx()
    ctx.channel.niche_config = None
    ctx.upstream['scene_breakdown']['scenes'] = [
        {'idx': 0, 'setting': 'Harbor'},
    ]
    fal_mock = AsyncMock(
        return_value={
            'url': 'https://fal.ai/est.jpg',
            'seed': 2,
            'content_policy_violation': False,
        },
    )
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.content = b'jpg'

    async def _inner() -> dict[str, object]:
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
            return await VisualAnchorsStage().run(ctx)

    result = asyncio.run(_inner())
    assert fal_mock.await_count == 1
    assert result['anchors'][0]['setting'] == 'harbor'  # type: ignore[index]
