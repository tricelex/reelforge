"""Apply ClipBrandTemplate settings onto candidate layout/style configs."""

from __future__ import annotations

import uuid
from typing import Any

from django.core.exceptions import ObjectDoesNotExist

from server.apps.clips.caption_presets import apply_caption_preset_to_style
from server.apps.clips.logic.constants import (
    TransitionStyle,
    WatermarkType,
)


def _apply_layout(candidate: Any, template: Any) -> None:
    layout = candidate.layout_config
    layout.render_format = template.render_format
    layout.render_mode = template.render_mode
    layout.fit_mode = template.fit_mode
    layout.foreground_treatment = template.foreground_treatment
    layout.background_mode = template.background_mode
    layout.background_color = template.background_color
    layout.blur_strength = template.blur_strength
    layout.save(
        update_fields=[
            'render_format',
            'render_mode',
            'fit_mode',
            'foreground_treatment',
            'background_mode',
            'background_color',
            'blur_strength',
            'updated_at',
        ],
    )


def _apply_logo(style: Any, template: Any) -> None:
    if template.logo_asset_id is None:
        return
    style.watermark_enabled = True
    style.watermark_type = WatermarkType.IMAGE
    style.watermark_image_id = template.logo_asset_id
    style.watermark_position = template.logo_position
    style.watermark_opacity = template.logo_opacity


def _apply_media(style: Any, template: Any) -> None:
    if template.intro_asset_id is not None:
        style.intro_asset_id = template.intro_asset_id
    if template.outro_asset_id is not None:
        style.outro_asset_id = template.outro_asset_id
    if template.music_asset_id is not None:
        style.music_enabled = True
        style.music_asset_id = template.music_asset_id
        style.music_volume_db = template.music_volume_db
    if template.auto_transitions:
        style.intro_transition = TransitionStyle.FADE_BLACK
        style.outro_transition = TransitionStyle.FADE_BLACK


def _apply_style(candidate: Any, template: Any) -> None:
    style = candidate.style_config
    if template.caption_preset_key:
        apply_caption_preset_to_style(style, template.caption_preset_key)
    _apply_logo(style, template)
    _apply_media(style, template)
    style.save()


def apply_brand_template_to_candidate(
    candidate: Any,
    template_id: str | None,
) -> bool:
    """Stamp layout and style from a brand template onto one candidate.

    Returns True when a template was found and applied.
    """
    if not template_id:
        return False
    from server.apps.clips.models import ClipBrandTemplate  # noqa: PLC0415

    try:
        template = ClipBrandTemplate.objects.get(
            id=uuid.UUID(str(template_id)),
            archived=False,
        )
    except (ObjectDoesNotExist, ValueError, TypeError):
        return False

    _apply_layout(candidate, template)
    _apply_style(candidate, template)
    return True
