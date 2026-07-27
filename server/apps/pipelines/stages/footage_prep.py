"""Footage prep stage — normalize sourced media into scene segments.

Output shape is identical to the motion stage so assembly consumes either
without branching.
"""

import asyncio
from typing import Any, override

import structlog

from server.apps.assets.models import AssetKind
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.apps.rendering import ffmpeg

logger = structlog.get_logger(__name__)


async def _load_asset_bytes(asset_id: str) -> bytes:
    """Read a stored Asset's bytes."""
    from server.apps.assets.models import Asset  # noqa: PLC0415

    asset = await Asset.objects.aget(id=asset_id)
    return await asyncio.to_thread(asset.file.read)


@register_stage
class FootagePrepStage(Stage):
    """Documentary stage: fit each sourced visual to its scene."""

    key = 'footage_prep'
    queue = 'render'
    max_retries = 2
    timeout_s = 600

    @override
    def fan_out(self, ctx: StageContext) -> list[dict[str, Any]] | None:
        """Shard by scene — one child per footage_search result."""
        shards = ctx.upstream.get('footage_search', {}).get('shards', [])
        scenes = {
            int(s['idx']): s
            for s in ctx.upstream.get('scene_breakdown', {}).get('scenes', [])
        }
        return [
            {
                'scene_idx': sh['scene_idx'],
                'asset_id': sh['asset_id'],
                'media_type': sh.get('media_type', 'image'),
                'est_seconds': float(
                    scenes.get(int(sh['scene_idx']), {}).get(
                        'est_seconds',
                        8.0,
                    ),
                ),
            }
            for sh in shards
        ]

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Normalize this shard's media into a video segment."""
        snap = ctx.execution.input_snapshot
        scene_idx = int(snap['scene_idx'])
        est_seconds = float(snap.get('est_seconds', 8.0))
        media_type = snap.get('media_type', 'image')
        logger.info(
            'footage_prep_started',
            run_id=str(ctx.run.id),
            scene_idx=scene_idx,
            media_type=media_type,
            est_seconds=est_seconds,
        )
        content = await _load_asset_bytes(str(snap['asset_id']))

        if media_type == 'video':
            video_bytes, method = await ffmpeg.normalize_clip(
                content,
                duration_s=est_seconds,
                width=ctx.config.get('target_width', 1920),
                height=ctx.config.get('target_height', 1080),
                fps=ctx.config.get('fps', 30),
            )
        else:
            video_bytes = await ffmpeg.ken_burns(
                image_bytes=content,
                duration_s=est_seconds,
                preset_idx=scene_idx,
            )
            method = 'ken_burns'

        asset = await ctx.assets.save(
            kind=AssetKind.VIDEO_SEGMENT,
            content=video_bytes,
            filename=f'scene_{scene_idx:04d}_{method}.mp4',
            mime='video/mp4',
        )
        logger.info(
            'footage_prep_completed',
            run_id=str(ctx.run.id),
            scene_idx=scene_idx,
            method=method,
            duration_s=est_seconds,
            asset_id=str(asset.id),
        )
        return {
            'scene_idx': scene_idx,
            'asset_id': str(asset.id),
            'duration_s': est_seconds,
            'method': method,
        }
