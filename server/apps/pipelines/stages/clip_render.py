"""ClipRenderStage — fan-out per approved candidate → run ClipRenderPipeline."""

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any, override

from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError


@register_stage
class ClipRenderStage(Stage):
    """Stage 5: fan-out per approved candidate → FINAL_VIDEO asset per shard."""

    key = 'clip_render'
    queue = 'render'
    max_retries = 1
    timeout_s = 3600

    @override
    def fan_out(self, ctx: StageContext) -> list[dict[str, Any]] | None:
        """Return one shard per approved candidate ID."""
        approved_ids: list[str] = ctx.upstream.get(
            'clip_approval_gate',
            {},
        ).get('approved_candidate_ids', [])
        if not approved_ids:
            raise FatalProviderError(
                'No candidates approved — approve at least one clip first.',
                provider='***REMOVED***',
            )
        return [{'candidate_id': cid} for cid in approved_ids]

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Run ClipRenderPipeline for one candidate; save FINAL_VIDEO asset."""
        from server.apps.assets.models import Asset, AssetKind  # noqa: PLC0415
        from server.apps.clips.logic.constants import (  # noqa: PLC0415
            render_format_dimensions,
        )
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415
        from server.apps.rendering.clip_render_pipeline import (  # noqa: PLC0415
            ClipRenderPipeline,
            PipelineRenderConfig,
        )

        candidate_id: str = ctx.execution.input_snapshot['candidate_id']
        source_asset_id: str = ctx.upstream['clip_ingest']['asset_id']
        manifest_asset_id: str = ctx.upstream['clip_transcribe'][
            'manifest_asset_id'
        ]

        candidate = await ClipCandidate.objects.select_related(
            'layout_config',
            'style_config',
        ).aget(id=candidate_id)
        timed_overlays = [o async for o in candidate.timed_overlays.all()]
        timed_sfx = [s async for s in candidate.timed_sfx.all()]

        source_asset = await Asset.objects.aget(id=source_asset_id)
        video_bytes = await asyncio.to_thread(source_asset.file.read)

        manifest_asset = await Asset.objects.aget(id=manifest_asset_id)
        manifest_bytes = await asyncio.to_thread(manifest_asset.file.read)
        manifest: dict[str, Any] = json.loads(manifest_bytes)
        transcript_json: dict[str, Any] = manifest.get('transcript_json', {})

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            src_path = tmp / 'source.mp4'
            out_path = tmp / 'rendered.mp4'
            await asyncio.to_thread(src_path.write_bytes, video_bytes)

            width, height = render_format_dimensions(
                candidate.layout_config.render_format,
            )
            config = PipelineRenderConfig(
                source_path=src_path,
                output_path=out_path,
                start_sec=candidate.start_sec,
                end_sec=candidate.end_sec,
                hook_text=candidate.hook_text,
                transcript_json=transcript_json,
                layout_config=candidate.layout_config,
                style_config=candidate.style_config,
                timed_overlays=timed_overlays,
                timed_sfx=timed_sfx,
                render_id=str(candidate.id),
                width=width,
                height=height,
            )
            await asyncio.to_thread(ClipRenderPipeline(config).run)
            rendered_bytes = await asyncio.to_thread(out_path.read_bytes)

        asset = await ctx.assets.save(
            kind=AssetKind.FINAL_VIDEO,
            content=rendered_bytes,
            filename=f'clip_{candidate_id}.mp4',
            mime='video/mp4',
        )
        candidate.render_asset_id = asset.id
        await candidate.asave(update_fields=['render_asset_id'])

        return {'candidate_id': candidate_id, 'asset_id': str(asset.id)}
