"""ClipPreviewRender stage — fan-out rough-cut MP4 per approved candidate.

Unlike ``clip_render`` this does not run the full styled render pipeline
(layout/captions/overlays) — it is a fast, re-encoded trim of the source
video meant only as an editor reference while the real cut happens in
DaVinci Resolve.
"""

import asyncio
import tempfile
from pathlib import Path
from typing import Any, override

from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError

_PREVIEW_CRF = 23
_PREVIEW_PRESET = 'veryfast'


async def _fetch_asset_bytes(asset_id: str) -> bytes:
    """Download bytes from an Asset by ID."""
    from server.apps.assets.models import Asset  # noqa: PLC0415

    asset = await Asset.objects.aget(id=asset_id)
    return await asyncio.to_thread(asset.file.read)


async def _run_rough_cut(
    *,
    source_path: str,
    out_path: str,
    start_sec: float,
    end_sec: float,
) -> None:
    """Re-encode ``[start_sec, end_sec)`` of the source into a preview MP4.

    Raises:
        RuntimeError: If ffmpeg exits non-zero.
    """
    from server.apps.rendering.ffmpeg import _run_ffmpeg_cmd  # noqa: PLC0415

    assert end_sec > start_sec, (  # noqa: S101
        'end_sec must be greater than start_sec'
    )
    assert start_sec >= 0, 'start_sec must be >= 0'  # noqa: S101
    cmd = [
        'ffmpeg',
        '-y',
        '-i',
        source_path,
        '-ss',
        f'{start_sec:.3f}',
        '-to',
        f'{end_sec:.3f}',
        '-c:v',
        'libx264',
        '-preset',
        _PREVIEW_PRESET,
        '-crf',
        str(_PREVIEW_CRF),
        '-c:a',
        'aac',
        '-movflags',
        '+faststart',
        out_path,
    ]
    await _run_ffmpeg_cmd(cmd, label='clip_preview_render')


@register_stage
class ClipPreviewRenderStage(Stage):
    """Terminal stage (clipping): rough-cut MP4 preview per approved clip."""

    key = 'clip_preview_render'
    queue = 'render'
    max_retries = 1
    timeout_s = 3600

    @override
    def fan_out(self, ctx: StageContext) -> list[dict[str, Any]] | None:
        """Return one shard per approved candidate ID (same as clip_render)."""
        approved_ids: list[str] = ctx.upstream.get(
            'clip_approval_gate',
            {},
        ).get('approved_candidate_ids', [])
        if not approved_ids:
            raise FatalProviderError(
                'No candidates approved — approve at least one clip first.',
                provider='reelforge',
            )
        return [
            {'candidate_id': cid, 'idx': i}
            for i, cid in enumerate(approved_ids)
        ]

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Render one rough-cut preview MP4 and save it as a FINAL_VIDEO."""
        from server.apps.assets.models import AssetKind  # noqa: PLC0415
        from server.apps.clips.models import (  # noqa: PLC0415
            ClipCandidate,
        )

        snap = ctx.execution.input_snapshot
        candidate_id: str = snap['candidate_id']
        shard_idx: int = int(snap.get('idx', 0))
        source_asset_id: str = ctx.upstream['clip_ingest']['asset_id']

        candidate = await ClipCandidate.objects.aget(id=candidate_id)
        video_bytes = await _fetch_asset_bytes(source_asset_id)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            src_path = tmp / 'source.mp4'
            out_path = tmp / 'preview.mp4'
            await asyncio.to_thread(src_path.write_bytes, video_bytes)
            await _run_rough_cut(
                source_path=str(src_path),
                out_path=str(out_path),
                start_sec=candidate.start_sec,
                end_sec=candidate.end_sec,
            )
            rendered_bytes = await asyncio.to_thread(out_path.read_bytes)

        assert rendered_bytes, 'rough cut produced empty video'  # noqa: S101
        asset = await ctx.assets.save(
            kind=AssetKind.FINAL_VIDEO,
            content=rendered_bytes,
            filename=f'clip_{shard_idx:02d}_preview.mp4',
            mime='video/mp4',
        )
        return {
            'candidate_id': candidate_id,
            'asset_id': str(asset.id),
            'start_sec': candidate.start_sec,
            'end_sec': candidate.end_sec,
        }
