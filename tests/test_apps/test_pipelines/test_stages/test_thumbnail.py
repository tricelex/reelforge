"""Tests for the thumbnail stage (Flux + Pillow compositing)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.thumbnail import (
    ThumbnailStage,
    _composite_text,
)


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run.topic = 'Fall of Rome'
    ctx.run.prompt_snapshot = {}
    ctx.channel.branding = MagicMock()
    ctx.channel.branding.thumbnail_palette = {
        'bg': '#CC0000',
        'text': '#FFFFFF',
    }
    ctx.upstream = {
        'metadata': {'title': 'How Rome REALLY Fell', 'tags': ['history']},
    }
    ctx.config = {'candidates': 2}
    ctx.costs = AsyncMock()
    ctx.assets = AsyncMock()
    ctx.assets.save = AsyncMock(return_value=MagicMock(id='thumb-uuid'))
    ctx.prompts.render = AsyncMock(return_value=('', ''))
    return ctx


def test_thumbnail_stage_key() -> None:
    """ThumbnailStage has the expected class attributes."""
    assert ThumbnailStage.key == 'thumbnail'
    assert ThumbnailStage.queue == 'api'


def test_thumbnail_fan_out_none() -> None:
    """Thumbnail is a single-execution stage."""
    assert ThumbnailStage().fan_out(MagicMock()) is None


def test_composite_text_returns_bytes() -> None:
    """_composite_text returns JPEG bytes with text overlay."""
    import io  # noqa: PLC0415

    from PIL import Image  # noqa: PLC0415

    img = Image.new('RGB', (100, 80), color=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    result = _composite_text(buf.getvalue(), 'ROME FALLS', {'text': '#FFFFFF'})
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_thumbnail_run_returns_candidates() -> None:
    """run() generates N thumbnail candidates and returns their asset IDs."""
    import httpx  # noqa: PLC0415

    ctx = _make_ctx()

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.fal.generate_image',
                new=AsyncMock(
                    return_value={
                        'url': 'https://fal.ai/thumb.jpg',
                        'seed': 99,
                        'content_policy_violation': False,
                    },
                ),
            ),
            patch(
                'httpx.AsyncClient.get',
                new=AsyncMock(
                    return_value=MagicMock(
                        spec=httpx.Response,
                        is_success=True,
                        content=b'fake-img',
                    ),
                ),
            ),
            patch(
                'server.apps.pipelines.stages.thumbnail._composite_text',
                return_value=b'fake-composited',
            ),
        ):
            return await ThumbnailStage().run(ctx)

    result = asyncio.run(_inner())
    assert 'candidates' in result
    assert len(result['candidates']) == 2  # type: ignore[arg-type]
    assert result['candidates'][0]['rank'] == 0  # type: ignore[index]


def test_thumbnail_run_with_no_branding_uses_empty_palette() -> None:
    """run() uses empty palette when ctx.channel.branding is None."""
    import httpx  # noqa: PLC0415

    ctx = _make_ctx()
    ctx.channel.branding = None
    ctx.config = {'candidates': 1}

    async def _inner() -> dict[str, object]:
        with (
            patch(
                'server.apps.generation.clients.fal.generate_image',
                new=AsyncMock(
                    return_value={
                        'url': 'https://fal.ai/thumb.jpg',
                        'seed': 1,
                        'content_policy_violation': False,
                    },
                ),
            ),
            patch(
                'httpx.AsyncClient.get',
                new=AsyncMock(
                    return_value=MagicMock(
                        spec=httpx.Response,
                        is_success=True,
                        content=b'fake-img',
                    ),
                ),
            ),
            patch(
                'server.apps.pipelines.stages.thumbnail._composite_text',
                return_value=b'fake-composited',
            ),
        ):
            return await ThumbnailStage().run(ctx)

    result = asyncio.run(_inner())
    assert 'candidates' in result
    assert len(result['candidates']) == 1  # type: ignore[arg-type]
