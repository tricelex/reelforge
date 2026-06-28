"""Tests for ClipIngestStage."""

import asyncio
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from server.apps.pipelines.stages.clip_ingest import (
    ClipIngestStage,
    _download_with_ytdlp,
)

_PROBE = {
    'streams': [
        {'codec_type': 'video', 'width': 1920, 'height': 1080},
    ],
}


def _ffprobe_patch() -> patch:
    return patch(
        'server.apps.rendering.ffmpeg.async_ffprobe',
        new=AsyncMock(return_value=_PROBE),
    )


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


def test_clip_ingest_linked_clip_source_uses_ingest_key() -> None:
    """Linked ClipSource supplies ingest key even when topic is a title."""
    ctx = MagicMock()
    ctx.run.id = uuid.uuid4()
    ctx.run.topic = 'Human Readable Title'
    ctx.run.prompt_snapshot = {'source_title': 'Human Readable Title'}

    fake_asset = MagicMock()
    fake_asset.id = 'asset-uuid-1'
    fake_asset.meta = {}
    fake_asset.asave = AsyncMock()
    fake_video_bytes = b'fake video bytes'
    fake_source = MagicMock()
    fake_source.title = 'Human Readable Title'
    fake_source.source_type = 'upload'
    fake_source.library_asset_id = uuid.uuid4()
    fake_source.url = ''

    async def _inner() -> dict:
        with (
            patch(
                'server.apps.pipelines.stages.clip_ingest.ClipSource.objects.filter',
            ) as mock_filter,
            patch(
                'server.apps.pipelines.stages.clip_ingest.resolve_ingest_key',
                return_value=str(fake_source.library_asset_id),
            ),
            patch(
                'server.apps.pipelines.stages.clip_ingest.asyncio.to_thread',
                new=AsyncMock(side_effect=[b'bytes', None, b'bytes']),
            ),
            _ffprobe_patch(),
            patch(
                'server.apps.assets.models.LibraryAsset',
            ) as mock_lib_cls,
        ):
            mock_filter.return_value.afirst = AsyncMock(return_value=fake_source)
            mock_lib_cls.objects.aget = AsyncMock(return_value=MagicMock())
            ctx.assets.save = AsyncMock(return_value=fake_asset)
            return await ClipIngestStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['source_title'] == 'Human Readable Title'
    assert result['source_url'] == str(fake_source.library_asset_id)


def test_clip_ingest_http_url() -> None:
    ctx = MagicMock()
    ctx.run.id = uuid.uuid4()
    ctx.run.topic = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
    ctx.run.prompt_snapshot = {}

    fake_asset = MagicMock()
    fake_asset.id = 'asset-uuid-1'
    fake_asset.meta = {}
    fake_asset.asave = AsyncMock()
    fake_video_bytes = b'fake video bytes'

    async def _inner() -> dict:
        with (
            patch(
                'server.apps.pipelines.stages.clip_ingest.ClipSource.objects.filter',
            ) as mock_filter,
            patch(
                'server.apps.pipelines.stages.clip_ingest.asyncio.to_thread',
                new=AsyncMock(
                    side_effect=[
                        {'title': 'Test Video', 'duration_sec': 300.0},
                        fake_video_bytes,
                    ],
                ),
            ),
            _ffprobe_patch(),
        ):
            mock_filter.return_value.afirst = AsyncMock(return_value=None)
            ctx.assets.save = AsyncMock(return_value=fake_asset)
            return await ClipIngestStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['asset_id'] == 'asset-uuid-1'
    assert result['source_title'] == 'Test Video'
    assert result['source_duration_sec'] == 300.0
    assert result['source_url'] == 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
    assert result['source_width'] == 1920
    assert result['source_height'] == 1080


def test_clip_ingest_library_asset_uuid() -> None:
    ctx = MagicMock()
    ctx.run.id = uuid.uuid4()
    ctx.run.topic = 'some-library-asset-uuid'
    ctx.run.prompt_snapshot = {'source_title': 'My Video'}

    fake_asset = MagicMock()
    fake_asset.id = 'pipeline-asset-uuid'
    fake_asset.meta = {}
    fake_asset.asave = AsyncMock()
    fake_lib_asset = MagicMock()

    async def _inner() -> dict:
        with (
            patch(
                'server.apps.pipelines.stages.clip_ingest.ClipSource.objects.filter',
            ) as mock_filter,
            patch(
                'server.apps.pipelines.stages.clip_ingest.asyncio.to_thread',
                new=AsyncMock(side_effect=[b'bytes', None, b'bytes']),
            ),
            _ffprobe_patch(),
            patch(
                'server.apps.assets.models.LibraryAsset',
            ) as mock_lib_cls,
        ):
            mock_filter.return_value.afirst = AsyncMock(return_value=None)
            mock_lib_cls.objects.aget = AsyncMock(return_value=fake_lib_asset)
            ctx.assets.save = AsyncMock(return_value=fake_asset)
            return await ClipIngestStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['source_title'] == 'My Video'
    assert result['source_duration_sec'] == 0.0


def test_clip_ingest_library_asset_default_title() -> None:
    ctx = MagicMock()
    ctx.run.id = uuid.uuid4()
    ctx.run.topic = 'some-uuid'
    ctx.run.prompt_snapshot = {}

    fake_asset = MagicMock()
    fake_asset.id = 'x'
    fake_asset.meta = {}
    fake_asset.asave = AsyncMock()
    fake_lib_asset = MagicMock()

    async def _inner() -> dict:
        with (
            patch(
                'server.apps.pipelines.stages.clip_ingest.ClipSource.objects.filter',
            ) as mock_filter,
            patch(
                'server.apps.pipelines.stages.clip_ingest.asyncio.to_thread',
                new=AsyncMock(side_effect=[b'bytes', None, b'bytes']),
            ),
            _ffprobe_patch(),
            patch(
                'server.apps.assets.models.LibraryAsset',
            ) as mock_lib_cls,
        ):
            mock_filter.return_value.afirst = AsyncMock(return_value=None)
            mock_lib_cls.objects.aget = AsyncMock(return_value=fake_lib_asset)
            ctx.assets.save = AsyncMock(return_value=fake_asset)
            return await ClipIngestStage().run(ctx)

    result = asyncio.run(_inner())
    assert result['source_title'] == 'Uploaded Video'


def test_download_with_ytdlp() -> None:
    mock_ydl = MagicMock()
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)
    mock_ydl.extract_info.return_value = {
        'title': 'Cool Video',
        'duration': 120,
    }

    fake_yt_dlp = MagicMock()
    fake_yt_dlp.YoutubeDL.return_value = mock_ydl

    with patch.dict(sys.modules, {'yt_dlp': fake_yt_dlp}):
        result = _download_with_ytdlp('https://example.com/v', '/tmp/out.mp4')

    assert result['title'] == 'Cool Video'
    assert result['duration_sec'] == 120.0
