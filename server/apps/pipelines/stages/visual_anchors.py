"""Visual anchors stage — one establishing still per unique setting."""

from typing import Any, override

import httpx

from server.apps.assets.models import AssetKind
from server.apps.generation.clients import fal as fal_client
from server.apps.pipelines.logic.scene_density import (
    MAX_SETTING_ANCHORS,
    select_anchor_settings,
)
from server.apps.pipelines.logic.visual_consistency import (
    FLUX_DEV,
    apply_visual_lock,
    build_visual_lock_prefix,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


def _niche_bits(channel: object) -> tuple[str, str]:
    """Lore and angle used to lock establishing shots."""
    from django.core.exceptions import ObjectDoesNotExist  # noqa: PLC0415

    try:
        niche = getattr(channel, 'niche_config', None)
    except ObjectDoesNotExist:
        return '', ''
    if niche is None:
        return '', ''
    return (
        str(getattr(niche, 'lore_document', '') or ''),
        str(getattr(niche, 'angle', '') or ''),
    )


@register_stage
class VisualAnchorsStage(Stage):
    """Generate master stills that later scene images Kontext-condition on."""

    key = 'visual_anchors'
    queue = 'api'
    max_retries = 3
    timeout_s = 600

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """One wide establishing shot per unique setting, capped."""
        scenes = ctx.upstream.get('scene_breakdown', {}).get('scenes', [])
        keys = select_anchor_settings(scenes, max_anchors=MAX_SETTING_ANCHORS)
        lore, angle = _niche_bits(ctx.channel)
        model = str(ctx.config.get('model') or FLUX_DEV)
        anchors: list[dict[str, Any]] = []
        for offset, setting in enumerate(keys):
            prefix = build_visual_lock_prefix(
                lore=lore,
                angle=angle,
                setting=setting,
                appearance='',
            )
            prompt, _negative = apply_visual_lock(
                (
                    f'Wide establishing shot of {setting}, cinematic 16:9, '
                    'photorealistic documentary still, locked lighting'
                ),
                prefix=prefix,
                negative='',
            )
            result = await fal_client.generate_image(
                prompt=prompt,
                model=model,
                width=1920,
                height=1080,
            )
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(result['url'])
                resp.raise_for_status()
                image_bytes = resp.content
            asset = await ctx.assets.save(
                kind=AssetKind.IMAGE,
                content=image_bytes,
                filename=f'setting_anchor_{offset:02d}.jpg',
                mime='image/jpeg',
            )
            file_url = ''
            if getattr(asset, 'file', None):
                file_url = asset.file.url
            anchors.append({
                'setting': setting,
                'asset_id': str(asset.id),
                'url': file_url or str(result['url']),
                'seed': result.get('seed'),
            })
            await ctx.costs.record(
                provider='fal_flux',
                operation='visual_anchor',
                units=1,
                unit_cost_usd=0.035,
            )
        return {'anchors': anchors}
