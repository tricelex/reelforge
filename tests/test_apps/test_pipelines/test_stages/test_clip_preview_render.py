"""Tests for ClipPreviewRenderStage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.apps.pipelines.stages.clip_preview_render import (
    ClipPreviewRenderStage,
    _fetch_asset_bytes,
    _run_rough_cut,
)
from server.common.exceptions import FatalProviderError

_MODULE = 'server.apps.pipelines.stages.clip_preview_render'


def test_clip_preview_render_attributes() -> None:
    assert ClipPreviewRenderStage.key == 'clip_preview_render'
    assert ClipPreviewRenderStage.queue == 'render'
    assert ClipPreviewRenderStage.max_retries == 1
    assert ClipPreviewRenderStage.timeout_s == 3600


def test_clip_preview_render_registered() -> None:
    from server.apps.pipelines.stages.base import STAGE_REGISTRY

    assert 'clip_preview_render' in STAGE_REGISTRY


class TestFetchAssetBytes:
    """Tests for _fetch_asset_bytes."""

    def test_reads_asset_file(self) -> None:
        """Bytes are read from the fetched Asset's file field."""
        mock_asset = MagicMock()
        mock_asset.file.read.return_value = b'video-bytes'

        async def _inner() -> bytes:
            with patch('server.apps.assets.models.Asset') as mock_cls:
                mock_cls.objects.aget = AsyncMock(return_value=mock_asset)
                return await _fetch_asset_bytes('asset-1')

        assert asyncio.run(_inner()) == b'video-bytes'


class TestRunRoughCut:
    """Tests for _run_rough_cut."""

    def test_invokes_ffmpeg_with_expected_args(self) -> None:
        """Ffmpeg is invoked with the trim window and encode settings."""
        mock_run = AsyncMock()

        async def _inner() -> None:
            with patch(
                'server.apps.rendering.ffmpeg._run_ffmpeg_cmd',
                new=mock_run,
            ):
                await _run_rough_cut(
                    source_path='/tmp/src.mp4',
                    out_path='/tmp/out.mp4',
                    start_sec=1.0,
                    end_sec=5.0,
                )

        asyncio.run(_inner())
        mock_run.assert_awaited_once()
        cmd = mock_run.call_args.args[0]
        assert cmd[0] == 'ffmpeg'
        assert '/tmp/src.mp4' in cmd
        assert '1.000' in cmd
        assert '5.000' in cmd
        assert mock_run.call_args.kwargs['label'] == 'clip_preview_render'

    def test_end_before_start_raises(self) -> None:
        """end_sec <= start_sec violates the precondition assertion."""

        async def _inner() -> None:
            await _run_rough_cut(
                source_path='/tmp/src.mp4',
                out_path='/tmp/out.mp4',
                start_sec=5.0,
                end_sec=1.0,
            )

        with pytest.raises(AssertionError):
            asyncio.run(_inner())

    def test_negative_start_raises(self) -> None:
        """A negative start_sec violates the precondition assertion."""

        async def _inner() -> None:
            await _run_rough_cut(
                source_path='/tmp/src.mp4',
                out_path='/tmp/out.mp4',
                start_sec=-1.0,
                end_sec=1.0,
            )

        with pytest.raises(AssertionError):
            asyncio.run(_inner())


class TestFanOut:
    """Tests for ClipPreviewRenderStage.fan_out."""

    def test_returns_one_shard_per_approved_candidate(self) -> None:
        """One shard dict is returned per approved candidate id."""
        ctx = MagicMock()
        ctx.upstream = {
            'clip_approval_gate': {
                'approved_candidate_ids': ['id-1', 'id-2'],
            },
        }
        shards = ClipPreviewRenderStage().fan_out(ctx)
        assert shards == [
            {'candidate_id': 'id-1', 'idx': 0},
            {'candidate_id': 'id-2', 'idx': 1},
        ]

    def test_no_approved_ids_raises(self) -> None:
        """No approved candidates raises FatalProviderError."""
        ctx = MagicMock()
        ctx.upstream = {'clip_approval_gate': {'approved_candidate_ids': []}}
        with pytest.raises(FatalProviderError, match='No candidates approved'):
            ClipPreviewRenderStage().fan_out(ctx)

    def test_missing_gate_key_raises(self) -> None:
        """A missing clip_approval_gate upstream also raises FatalProviderError."""
        ctx = MagicMock()
        ctx.upstream = {}
        with pytest.raises(FatalProviderError):
            ClipPreviewRenderStage().fan_out(ctx)


class TestRun:
    """Tests for ClipPreviewRenderStage.run."""

    def test_renders_and_saves_preview(self) -> None:
        """A rough-cut preview is rendered and saved as a FINAL_VIDEO asset."""
        ctx = MagicMock()
        ctx.execution.input_snapshot = {'candidate_id': 'cand-1', 'idx': 2}
        ctx.upstream = {'clip_ingest': {'asset_id': 'src-asset-id'}}

        fake_candidate = MagicMock()
        fake_candidate.start_sec = 3.0
        fake_candidate.end_sec = 9.0

        fake_asset = MagicMock()
        fake_asset.id = 'preview-asset-uuid'
        ctx.assets.save = AsyncMock(return_value=fake_asset)

        async def _inner() -> dict:
            with (
                patch(
                    'server.apps.clips.models.ClipCandidate',
                ) as mock_cand_cls,
                patch(
                    f'{_MODULE}._fetch_asset_bytes',
                    new=AsyncMock(return_value=b'source-video-bytes'),
                ),
                patch(f'{_MODULE}._run_rough_cut', new=AsyncMock()),
                patch(
                    f'{_MODULE}.asyncio.to_thread',
                    new=AsyncMock(
                        side_effect=[None, b'rendered-preview-bytes'],
                    ),
                ),
            ):
                mock_cand_cls.objects.aget = AsyncMock(
                    return_value=fake_candidate,
                )
                return await ClipPreviewRenderStage().run(ctx)

        result = asyncio.run(_inner())
        assert result == {
            'candidate_id': 'cand-1',
            'asset_id': 'preview-asset-uuid',
            'start_sec': 3.0,
            'end_sec': 9.0,
        }
        ctx.assets.save.assert_awaited_once()
        assert (
            ctx.assets.save.call_args.kwargs['filename']
            == 'clip_02_preview.mp4'
        )

    def test_default_shard_idx_when_missing(self) -> None:
        """A missing idx in the input snapshot defaults to shard 0."""
        ctx = MagicMock()
        ctx.execution.input_snapshot = {'candidate_id': 'cand-1'}
        ctx.upstream = {'clip_ingest': {'asset_id': 'src-asset-id'}}

        fake_candidate = MagicMock()
        fake_candidate.start_sec = 0.0
        fake_candidate.end_sec = 2.0
        fake_asset = MagicMock()
        fake_asset.id = 'preview-uuid-2'
        ctx.assets.save = AsyncMock(return_value=fake_asset)

        async def _inner() -> dict:
            with (
                patch(
                    'server.apps.clips.models.ClipCandidate',
                ) as mock_cand_cls,
                patch(
                    f'{_MODULE}._fetch_asset_bytes',
                    new=AsyncMock(return_value=b'source-video-bytes'),
                ),
                patch(f'{_MODULE}._run_rough_cut', new=AsyncMock()),
                patch(
                    f'{_MODULE}.asyncio.to_thread',
                    new=AsyncMock(side_effect=[None, b'rendered-bytes']),
                ),
            ):
                mock_cand_cls.objects.aget = AsyncMock(
                    return_value=fake_candidate,
                )
                return await ClipPreviewRenderStage().run(ctx)

        result = asyncio.run(_inner())
        assert (
            ctx.assets.save.call_args.kwargs['filename']
            == 'clip_00_preview.mp4'
        )
        assert result['candidate_id'] == 'cand-1'
