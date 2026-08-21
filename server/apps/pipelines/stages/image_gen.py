"""Image gen stage — fan-out per scene, Flux via fal.ai."""

from typing import Any, override

import httpx
import structlog

from server.apps.assets.models import AssetKind
from server.apps.generation.clients import fal as fal_client
from server.apps.pipelines.logic.scene_density import normalize_setting
from server.apps.pipelines.logic.visual_consistency import (
    FLUX_DEV,
    is_kontext_model,
    merge_style_negatives,
    niche_style_fields,
    resolve_image_route,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError

logger = structlog.get_logger(__name__)


async def _library_ref_url(ref_id: object, scene_idx: int) -> str | None:
    """Resolve a Character.hero_ref LibraryAsset id to a public file URL."""
    from server.apps.assets.models import LibraryAsset  # noqa: PLC0415

    try:
        ref_asset = await LibraryAsset.objects.aget(id=str(ref_id))
    except LibraryAsset.DoesNotExist:
        logger.warning(
            'image_gen_character_ref_missing',
            character_ref_id=str(ref_id),
            scene_idx=scene_idx,
        )
        return None
    if not ref_asset.file:
        logger.warning(
            'image_gen_character_ref_empty_file',
            character_ref_id=str(ref_id),
            scene_idx=scene_idx,
        )
        return None
    return str(ref_asset.file.url)


def _anchor_url_map(ctx: StageContext) -> dict[str, str]:
    """Setting key → establishing-shot URL from visual_anchors."""
    anchors = ctx.upstream.get('visual_anchors', {}).get('anchors', [])
    mapping: dict[str, str] = {}
    for row in anchors:
        key = normalize_setting(str(row.get('setting') or ''))
        url = str(row.get('url') or '')
        if key and url:
            mapping[key] = url
    return mapping


def _scene_setting_map(ctx: StageContext) -> dict[int, str]:
    """Scene idx → setting string from scene_breakdown."""
    scenes = ctx.upstream.get('scene_breakdown', {}).get('scenes', [])
    return {
        int(scene['idx']): str(scene.get('setting') or '')
        for scene in scenes
        if 'idx' in scene
    }


def _prepare_kontext_prompt(prompt: str, negative: str) -> tuple[str, str]:
    """Kontext has no negative_prompt field; bake avoid-text into prompt."""
    prepared = (
        'Keep identity and location from the reference image(s). '
        'Change only camera, lens, and subject action.\n'
        f'{prompt}'
    )
    if negative:
        prepared = f'{prepared}\nAvoid: {negative}'
    return prepared, ''


def _channel_style_negatives(channel: object) -> list[str]:
    """Niche style_negatives, empty when the channel has no niche."""
    from django.core.exceptions import ObjectDoesNotExist  # noqa: PLC0415

    try:
        niche = getattr(channel, 'niche_config', None)
    except ObjectDoesNotExist:
        return []
    _style, _angle, _medium, negatives = niche_style_fields(niche)
    return negatives


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
        anchors = _anchor_url_map(ctx)
        settings = _scene_setting_map(ctx)
        shards: list[dict[str, Any]] = []
        for prompt in prompts:
            scene_idx = int(prompt['scene_idx'])
            setting_key = normalize_setting(settings.get(scene_idx, ''))
            shards.append({
                'scene_idx': scene_idx,
                'prompt': prompt['prompt'],
                'negative_prompt': prompt.get('negative_prompt', ''),
                'safety_flagged': prompt.get('safety_flagged', False),
                'character_ref_id': prompt.get('character_ref_id'),
                'setting_anchor_url': anchors.get(setting_key),
            })
        return shards

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Generate and save one image for this child shard's scene."""
        snap = ctx.execution.input_snapshot
        scene_idx: int = snap['scene_idx']
        prompt: str = snap['prompt']
        negative: str = merge_style_negatives(
            snap.get('negative_prompt', ''),
            _channel_style_negatives(ctx.channel),
        )
        safety_flagged: bool = snap.get('safety_flagged', False)

        if safety_flagged:
            raise FatalProviderError(
                f'Scene {scene_idx} prompt pre-flagged for safety',
                provider='flux',
                error_code='safety_preflag',
            )

        character_url: str | None = None
        use_ref = bool(ctx.config.get('use_character_ref'))
        if use_ref:
            ref_id = snap.get('character_ref_id')
            if ref_id:
                character_url = await _library_ref_url(ref_id, scene_idx)
        route = resolve_image_route(
            character_url=character_url,
            setting_url=snap.get('setting_anchor_url'),
            use_character_ref=use_ref,
            default_model=str(ctx.config.get('model') or FLUX_DEV),
        )
        gen_prompt, gen_negative = prompt, negative
        if is_kontext_model(route.model):
            gen_prompt, gen_negative = _prepare_kontext_prompt(
                prompt,
                negative,
            )
        result = await fal_client.generate_image(
            prompt=gen_prompt,
            model=route.model,
            negative_prompt=gen_negative,
            width=1920,
            height=1080,
            image_url=route.image_url,
            image_urls=route.image_urls,
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
        unit_cost = 0.04 if is_kontext_model(route.model) else 0.035
        await ctx.costs.record(
            provider='fal_flux',
            operation='image_gen',
            units=1,
            unit_cost_usd=unit_cost,
        )
        return {
            'scene_idx': scene_idx,
            'asset_id': str(asset.id),
            'seed': result.get('seed'),
        }
