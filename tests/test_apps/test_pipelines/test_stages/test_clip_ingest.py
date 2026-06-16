"""Tests for ClipIngestStage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.clip_ingest import ClipIngestStage


def test_clip_ingest_attributes() -> None:
    assert ClipIngestStage.key == 'clip_ingest'
    assert ClipIngestStage.queue == 'render'
    assert ClipIngestStage.max_retries == 3
    assert ClipIngestStage.timeout_s == 1800


def test_clip_ingest_fan_out_returns_none() -> None:
    assert ClipIngestStage().fan_out(MagicMock()) is None


def test_clip_ingest_registered() -> None:
    from server.apps.pipelines.stages.base import STAGE_REGISTRY

    assert 'clip_ingest' in STAGE_REGISTRY


def test_clip_ingest_http_url() -> None:
    ctx = MagicMock()
    ctx.run.topic = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
    ctx.run.prompt_snapshot = {}

    fake_asset = MagicMock()
    fake_asset.id = 'asset-uuid-1'
    fake_video_bytes = b'fake video bytes'

    async def _inner() -> dict:
        with patch(
            'server.apps.pipelines.stages.clip_ingest.asyncio.to_thread',
            new=AsyncMock(side_effect=[
                {'title': 'Test Video', 'duration_sec': 300.0},
                fake_video_bytes,
            ]),
        ):
            ctx.assets.save = AsyncMock(return_value=fake_asset)
            return await ClipIngestStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['asset_id'] == 'asset-uuid-1'
    assert result['source_title'] == 'Test Video'
    assert result['source_duration_sec'] == 300.0
    assert result['source_url'] == 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'


def test_clip_ingest_library_asset_uuid() -> None:
    ctx = MagicMock()
    ctx.run.topic = 'some-library-asset-uuid'
    ctx.run.prompt_snapshot = {'source_title': 'My Video'}

    fake_asset = MagicMock()
    fake_asset.id = 'pipeline-asset-uuid'
    fake_lib_asset = MagicMock()

    async def _inner() -> dict:
        with (
            patch(
                'server.apps.pipelines.stages.clip_ingest.asyncio.to_thread',
                new=AsyncMock(side_effect=[b'bytes', None, b'bytes']),
            ),
            patch(
                'server.apps.assets.models.LibraryAsset',
            ) as mock_lib_cls,
        ):
            mock_lib_cls.objects.aget = AsyncMock(return_value=fake_lib_asset)
            ctx.assets.save = AsyncMock(return_value=fake_asset)
            return await ClipIngestStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['source_title'] == 'My Video'
    assert result['source_duration_sec'] == 0.0


def test_clip_ingest_library_asset_default_title() -> None:
    ctx = MagicMock()
    ctx.run.topic = 'some-uuid'
    ctx.run.prompt_snapshot = {}

    fake_asset = MagicMock()
    fake_asset.id = 'x'
    fake_lib_asset = MagicMock()

    async def _inner() -> dict:
        with (
            patch(
                'server.apps.pipelines.stages.clip_ingest.asyncio.to_thread',
                new=AsyncMock(side_effect=[b'bytes', None, b'bytes']),
            ),
            patch(
                'server.apps.assets.models.LibraryAsset',
            ) as mock_lib_cls,
        ):
            mock_lib_cls.objects.aget = AsyncMock(return_value=fake_lib_asset)
            ctx.assets.save = AsyncMock(return_value=fake_asset)
            return await ClipIngestStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['source_title'] == 'Uploaded Video'
