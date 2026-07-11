"""Thumbnail stage — Flux generation + Pillow text composite."""

import io
from typing import Any, override

import httpx

from server.apps.assets.models import AssetKind
from server.apps.generation.clients import fal as fal_client
from server.apps.pipelines.services.prompt_variables import (
    build_prompt_variables,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)

_THUMBNAIL_MODEL = 'fal-ai/flux/dev'
_THUMBNAIL_PROMPT_SUFFIX = (
    ', thumbnail style, bold typography space, exaggerated emotion, '
    'rule of thirds, high contrast, 16:9 aspect ratio, 1920x1080'
)


def _composite_text(
    image_bytes: bytes,
    title: str,
    palette: dict[str, Any],
) -> bytes:
    """Overlay 2-4 word bold text onto the image using Pillow."""
    from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415

    img = Image.open(io.BytesIO(image_bytes)).convert('RGBA')
    draw = ImageDraw.Draw(img)

    words = title.split()[:4]
    text = ' '.join(words).upper()
    text_color: str = palette.get('text', '#FFFFFF')

    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    try:
        font = ImageFont.truetype(
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            120,
        )
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    x = (img.width - text_w) // 2
    y = img.height - 200

    draw.text((x + 3, y + 3), text, fill='#00000088', font=font)
    draw.text((x, y), text, fill=text_color, font=font)

    out = io.BytesIO()
    img.convert('RGB').save(out, format='JPEG', quality=95)
    return out.getvalue()


@register_stage
class ThumbnailStage(Stage):
    """Stage 11: generate thumbnail candidates (Flux + Pillow text overlay)."""

    key = 'thumbnail'
    queue = 'api'
    max_retries = 3
    timeout_s = 300

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Generate N thumbnail candidates and return their asset IDs."""
        metadata = ctx.upstream.get('metadata', {})
        title: str = metadata.get('title', ctx.run.topic)
        n_candidates = ctx.config.get('candidates', 3)
        palette: dict[str, Any] = {}
        branding = getattr(ctx.channel, 'branding', None)
        if branding:
            palette = getattr(branding, 'thumbnail_palette', {}) or {}

        variables = await build_prompt_variables(
            ctx,
            extra={'title': title},
        )
        _, usr = await ctx.prompts.render('thumbnail', variables)
        thumb_prompt = usr or (
            f'Cinematic thumbnail for: {title}. '
            f'Exaggerated emotion, dramatic lighting, photorealistic.'
            f'{_THUMBNAIL_PROMPT_SUFFIX}'
        )

        candidates: list[dict[str, Any]] = []
        for rank in range(n_candidates):
            result = await fal_client.generate_image(
                prompt=thumb_prompt,
                model=_THUMBNAIL_MODEL,
                width=1920,
                height=1080,
            )
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(result['url'])
                resp.raise_for_status()
                raw_bytes = resp.content

            composited = _composite_text(raw_bytes, title, palette)
            asset = await ctx.assets.save(
                kind=AssetKind.THUMBNAIL,
                content=composited,
                filename=f'thumbnail_{rank}.jpg',
                mime='image/jpeg',
            )
            await ctx.costs.record(
                provider='fal_flux',
                operation='thumbnail_gen',
                units=1,
                unit_cost_usd=0.035,
            )
            candidates.append({'rank': rank, 'asset_id': str(asset.id)})

        return {'candidates': candidates}
