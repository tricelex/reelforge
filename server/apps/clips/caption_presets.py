"""Seeded caption style presets for brand templates and the clip editor."""

from __future__ import annotations

from typing import Any, Final

from server.apps.clips.logic.constants import (
    CaptionAnimation,
    CaptionFont,
    CaptionPosition,
    CaptionStyle,
)

CAPTION_PRESETS: Final[tuple[dict[str, Any], ...]] = (
    {
        'key': 'karaoke',
        'name': 'Karaoke',
        'description': 'Word-by-word highlight with bold Montserrat.',
        'caption_style': CaptionStyle.KARAOKE_HIGHLIGHT,
        'caption_font': CaptionFont.MONTSERRAT_BOLD,
        'caption_size': 64,
        'caption_color': '#FFFFFF',
        'caption_highlight_color': '#FFE566',
        'caption_stroke_color': '#000000',
        'caption_stroke_width': 4,
        'caption_position': CaptionPosition.CENTER,
        'caption_animation': CaptionAnimation.POP,
        'caption_uppercase': True,
        'sample_phrase': 'TO GET STARTED',
    },
    {
        'key': 'word_pop',
        'name': 'Word Pop',
        'description': 'Single-word punches for high energy hooks.',
        'caption_style': CaptionStyle.WORD_BY_WORD,
        'caption_font': CaptionFont.ANTON,
        'caption_size': 72,
        'caption_color': '#FFFFFF',
        'caption_highlight_color': '#FF4D6D',
        'caption_stroke_color': '#111111',
        'caption_stroke_width': 5,
        'caption_position': CaptionPosition.CENTER,
        'caption_animation': CaptionAnimation.POP,
        'caption_uppercase': True,
        'sample_phrase': 'WATCH THIS',
    },
    {
        'key': 'chunk_three',
        'name': 'Chunk 3',
        'description': 'Readable three-word phrases for talking heads.',
        'caption_style': CaptionStyle.CHUNKED,
        'caption_font': CaptionFont.POPPINS_BOLD,
        'caption_size': 56,
        'caption_color': '#FFFFFF',
        'caption_highlight_color': '#00E5A8',
        'caption_stroke_color': '#000000',
        'caption_stroke_width': 3,
        'caption_position': CaptionPosition.BOTTOM,
        'caption_animation': CaptionAnimation.FADE,
        'caption_uppercase': False,
        'sample_phrase': 'feel full longer',
    },
    {
        'key': 'lower_third',
        'name': 'Lower Third',
        'description': 'Full-segment captions for podcast clarity.',
        'caption_style': CaptionStyle.LOWER_THIRD,
        'caption_font': CaptionFont.INTER_BOLD,
        'caption_size': 42,
        'caption_color': '#F8FAFC',
        'caption_highlight_color': '#38BDF8',
        'caption_stroke_color': '#0F172A',
        'caption_stroke_width': 2,
        'caption_position': CaptionPosition.BOTTOM,
        'caption_animation': CaptionAnimation.FADE,
        'caption_uppercase': False,
        'sample_phrase': 'Here is the key insight',
    },
    {
        'key': 'emoji_accent',
        'name': 'Emoji Accent',
        'description': 'Chunked captions with keyword emoji accents.',
        'caption_style': CaptionStyle.EMOJI_ACCENT,
        'caption_font': CaptionFont.BANGERS,
        'caption_size': 58,
        'caption_color': '#FFFFFF',
        'caption_highlight_color': '#FACC15',
        'caption_stroke_color': '#000000',
        'caption_stroke_width': 3,
        'caption_position': CaptionPosition.CENTER,
        'caption_animation': CaptionAnimation.POP,
        'caption_uppercase': True,
        'sample_phrase': 'PROTEIN BAR PERFECT',
    },
    {
        'key': 'mozi',
        'name': 'Mozi',
        'description': 'Tight center captions with warm highlight.',
        'caption_style': CaptionStyle.CHUNKED,
        'caption_font': CaptionFont.OSWALD_BOLD,
        'caption_size': 60,
        'caption_color': '#FFF7ED',
        'caption_highlight_color': '#FB923C',
        'caption_stroke_color': '#1C1917',
        'caption_stroke_width': 4,
        'caption_position': CaptionPosition.CENTER,
        'caption_animation': CaptionAnimation.POP,
        'caption_uppercase': True,
        'sample_phrase': 'LOW CALORIE HIGH PROTEIN',
    },
    {
        'key': 'seamless_bounce',
        'name': 'Seamless Bounce',
        'description': 'Playful bounce-style captions for lifestyle clips.',
        'caption_style': CaptionStyle.WORD_BY_WORD,
        'caption_font': CaptionFont.RIGHTEOUS,
        'caption_size': 66,
        'caption_color': '#ECFEFF',
        'caption_highlight_color': '#22D3EE',
        'caption_stroke_color': '#083344',
        'caption_stroke_width': 4,
        'caption_position': CaptionPosition.CENTER,
        'caption_animation': CaptionAnimation.POP,
        'caption_uppercase': True,
        'sample_phrase': 'BEAT HUNGER',
    },
)


def list_caption_presets() -> list[dict[str, Any]]:
    """Return all caption presets as plain dictionaries."""
    return [dict(preset) for preset in CAPTION_PRESETS]


def get_caption_preset(key: str) -> dict[str, Any] | None:
    """Return one caption preset by key, or None."""
    assert key, 'preset key is required'  # noqa: S101
    for preset in CAPTION_PRESETS:
        if preset['key'] == key:
            return dict(preset)
    return None


def apply_caption_preset_to_style(
    style: Any,
    preset_key: str,
) -> bool:
    """Apply a caption preset onto a ClipStyleConfig instance.

    Returns True when the preset was found and applied.
    """
    preset = get_caption_preset(preset_key)
    if preset is None:
        return False
    style.caption_enabled = True
    style.caption_style = preset['caption_style']
    style.caption_font = preset['caption_font']
    style.caption_size = preset['caption_size']
    style.caption_color = preset['caption_color']
    style.caption_highlight_color = preset['caption_highlight_color']
    style.caption_stroke_color = preset['caption_stroke_color']
    style.caption_stroke_width = preset['caption_stroke_width']
    style.caption_position = preset['caption_position']
    style.caption_animation = preset['caption_animation']
    style.caption_uppercase = preset['caption_uppercase']
    return True
