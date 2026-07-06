from server.apps.clips.logic.constants import (
    CaptionFont,
    CaptionStyle,
    ColorFilterPreset,
    FitMode,
    OverlayAnimation,
    OverlayShape,
    OverlayType,
    TransitionStyle,
    WatermarkPosition,
)


def test_caption_font_has_sixteen_curated_values() -> None:
    assert len(CaptionFont.values) == 16
    assert 'MONTSERRAT_BOLD' in CaptionFont.values
    assert 'PACIFICO' in CaptionFont.values


def test_transition_style_has_full_capcut_palette() -> None:
    expected = {
        'NONE', 'CROSSFADE', 'FADE_BLACK', 'FADE_WHITE',
        'SLIDE_LEFT', 'SLIDE_RIGHT', 'SLIDE_UP', 'SLIDE_DOWN',
        'WIPE_LEFT', 'WIPE_RIGHT', 'ZOOM_IN', 'CUSTOM_ASSET',
    }
    assert set(TransitionStyle.values) == expected


def test_watermark_position_has_center_and_tiled() -> None:
    assert 'CENTER' in WatermarkPosition.values
    assert 'TILED' in WatermarkPosition.values


def test_caption_style_has_karaoke_highlight() -> None:
    assert 'KARAOKE_HIGHLIGHT' in CaptionStyle.values


def test_overlay_type_has_video() -> None:
    assert 'VIDEO' in OverlayType.values


def test_overlay_animation_values() -> None:
    assert set(OverlayAnimation.values) == {
        'NONE', 'FADE', 'POP',
        'SLIDE_LEFT', 'SLIDE_RIGHT', 'SLIDE_UP', 'SLIDE_DOWN',
    }


def test_color_filter_preset_values() -> None:
    assert set(ColorFilterPreset.values) == {
        'NONE', 'VIVID', 'MOODY', 'WARM', 'COOL', 'BLACK_WHITE', 'VINTAGE',
    }


def test_fit_mode_values() -> None:
    assert set(FitMode.values) == {'CROP', 'BLUR_FILL'}


def test_overlay_shape_values() -> None:
    assert set(OverlayShape.values) == {'RECTANGLE', 'CIRCLE', 'ROUNDED'}
