"""Tests for caption presets."""

from server.apps.clips.caption_presets import (
    apply_caption_preset_to_style,
    get_caption_preset,
    list_caption_presets,
)


def test_list_caption_presets_non_empty() -> None:
    presets = list_caption_presets()
    assert len(presets) >= 5
    assert all('key' in p and 'sample_phrase' in p for p in presets)


def test_get_caption_preset_known_and_unknown() -> None:
    assert get_caption_preset('karaoke') is not None
    assert get_caption_preset('missing') is None


def test_apply_caption_preset_to_style() -> None:
    class _Style:
        caption_enabled = False
        caption_style = ''
        caption_font = ''
        caption_size = 0
        caption_color = ''
        caption_highlight_color = ''
        caption_stroke_color = ''
        caption_stroke_width = 0
        caption_position = ''
        caption_animation = ''
        caption_uppercase = False

    style = _Style()
    assert apply_caption_preset_to_style(style, 'karaoke') is True
    assert style.caption_enabled is True
    assert style.caption_style == 'KARAOKE_HIGHLIGHT'
    assert apply_caption_preset_to_style(style, 'nope') is False
