"""Image gen stage — fan-out per scene, Flux via fal.ai."""

from typing import Any, override

import httpx

from server.apps.assets.models import AssetKind
from server.apps.generation.clients import fal as fal_client
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError


@register_stage
class ImageGenStage(Stage):
    """Stage 6: generate one image per scene (fan-out)."""

    key = 'image_gen'
    queue = 'api'
    max_retries = 3
    timeout_s = 300

    @override
    def fan_out(self, ctx: StageContext) -> list[dict[str, Any]] | None:
        """Shard by visual prompt — one child per scene."""
        prompts = ctx.upstream.get('visual_prompts', {}).get('prompts', [])
        return [
            {
                'scene_idx': p['scene_idx'],
                'prompt': p['prompt'],
                'negative_prompt': p.get('negative_prompt', ''),
                'safety_flagged': p.get('safety_flagged', False),
                'character_ref_id': p.get('character_ref_id'),
            }
            for p in prompts
        ]

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Generate and save one image for this child shard's scene."""
        snap = ctx.execution.input_snapshot
        scene_idx: int = snap['scene_idx']
        prompt: str = snap['prompt']
        negative: str = snap.get('negative_prompt', '')
        safety_flagged: bool = snap.get('safety_flagged', False)

        if safety_flagged:
            raise FatalProviderError(
                f'Scene {scene_idx} prompt pre-flagged for safety',
                provider='flux',
                error_code='safety_preflag',
            )

        model = ctx.config.get('model', 'fal-ai/flux/dev')
        image_url: str | None = None
        if ctx.config.get('use_character_ref'):
            ref_id = snap.get('character_ref_id')
            if ref_id:
                from server.apps.assets.models import Asset  # noqa: PLC0415

                ref_asset = await Asset.objects.aget(id=ref_id)
                image_url = ref_asset.file.url if ref_asset.file else None
        result = await fal_client.generate_image(
            prompt=prompt,
            model=model,
            negative_prompt=negative,
            width=1920,
            height=1080,
            image_url=image_url,
        )

        if result.get('content_policy_violation'):
            raise FatalProviderError(
                f'Scene {scene_idx} safety filter triggered',
                provider='flux',
                error_code='safety_filter',
            )

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(result['url'])
            resp.raise_for_status()
            image_bytes = resp.content

        asset = await ctx.assets.save(
            kind=AssetKind.IMAGE,
            content=image_bytes,
            filename=f'scene_{scene_idx:04d}.jpg',
            mime='image/jpeg',
        )
        await ctx.costs.record(
            provider='fal_flux',
            operation='image_gen',
            units=1,
            unit_cost_usd=0.035,
        )
        return {
            'scene_idx': scene_idx,
            'asset_id': str(asset.id),
            'seed': result.get('seed'),
        }
