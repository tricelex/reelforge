"""Tests for layout composition validation helpers."""

import pytest
from django.core.exceptions import ValidationError

from server.apps.clips.logic.composition import (
    apply_legacy_fit_mode,
    fit_mode_from_composition,
    normalize_background_color,
    normalize_blur_strength,
    resolve_composition,
)
from server.apps.rendering.clip_stages.composition import (
    middle_zone,
    resolve_layout_composition,
)


def test_normalize_background_color_accepts_hex() -> None:
    assert normalize_background_color('#aabbcc') == '#AABBCC'


def test_normalize_background_color_rejects_invalid() -> None:
    with pytest.raises(ValidationError, match='Invalid background_color'):
        normalize_background_color('red')


def test_normalize_blur_strength_bounds() -> None:
    assert normalize_blur_strength(1) == 1
    assert normalize_blur_strength(50) == 50
    with pytest.raises(ValidationError, match='blur_strength'):
        normalize_blur_strength(0)
    with pytest.raises(ValidationError, match='blur_strength'):
        normalize_blur_strength(51)


def test_fit_mode_from_composition() -> None:
    assert (
        fit_mode_from_composition(
            foreground_treatment='CONTAIN',
            background_mode='BLURRED_SOURCE',
        )
        == 'BLUR_FILL'
    )
    assert (
        fit_mode_from_composition(
            foreground_treatment='FILL',
            background_mode='SOLID',
        )
        == 'CROP'
    )


def test_apply_legacy_fit_mode_blur_fill() -> None:
    treatment, mode, color, blur = apply_legacy_fit_mode(fit_mode='BLUR_FILL')
    assert treatment == 'CONTAIN'
    assert mode == 'BLURRED_SOURCE'
    assert color == '#000000'
    assert blur == 20


def test_resolve_composition_prefers_explicit_fields() -> None:
    treatment, mode, color, blur = resolve_composition(
        foreground_treatment='SQUARE_CROP',
        background_mode='SOLID',
        background_color='#123456',
        blur_strength=12,
        fit_mode='BLUR_FILL',
    )
    assert treatment == 'SQUARE_CROP'
    assert mode == 'SOLID'
    assert color == '#123456'
    assert blur == 12


def test_middle_zone_portrait() -> None:
    zone = middle_zone(1080, 1920)
    assert zone.size == 1080
    assert zone.x == 0
    assert zone.y == 420


def test_resolve_layout_composition_legacy_blur_fill() -> None:
    class _Layout:
        foreground_treatment = 'FILL'
        background_mode = 'SOLID'
        background_color = '#000000'
        blur_strength = 20
        fit_mode = 'BLUR_FILL'

    resolved = resolve_layout_composition(_Layout())
    assert resolved.foreground_treatment == 'CONTAIN'
    assert resolved.background_mode == 'BLURRED_SOURCE'


def test_middle_zone_rejects_invalid_size() -> None:
    with pytest.raises(ValueError, match='positive'):
        middle_zone(0, 1080)


def test_filter_builders() -> None:
    from server.apps.rendering.clip_stages.composition import (
        blurred_background_filter,
        compose_overlay_filter,
        contain_foreground_filter,
        fill_crop_filter,
        solid_background_filter,
        square_crop_foreground_filter,
    )

    zone = middle_zone(1080, 1920)
    solid = solid_background_filter(
        width=1080,
        height=1920,
        color='#010203',
        duration_sec=2.5,
    )
    assert 'color=c=#010203:s=1080x1920:d=2.500000' in solid
    blur = blurred_background_filter(
        width=1080,
        height=1920,
        blur_strength=12,
    )
    assert 'boxblur=12:5' in blur
    assert 'force_original_aspect_ratio=decrease' in contain_foreground_filter(
        zone=zone,
    )
    assert "crop='min(iw,ih)'" in square_crop_foreground_filter(
        zone=zone,
        crop_x=None,
        crop_y=None,
        crop_w=None,
        crop_h=None,
    )
    assert 'crop=100:100:10:20' in square_crop_foreground_filter(
        zone=zone,
        crop_x=10,
        crop_y=20,
        crop_w=100,
        crop_h=120,
    )
    assert fill_crop_filter(width=1080, height=1920).startswith("crop='min")
    overlay = compose_overlay_filter(zone=zone, video_suffix='', fps=30)
    assert 'overlay=0+(1080-w)/2:420+(1080-h)/2' in overlay


def test_composition_helpers_reject_invalid_inputs() -> None:
    from server.apps.rendering.clip_stages.composition import (
        blurred_background_filter,
        resolve_layout_composition,
        solid_background_filter,
    )

    with pytest.raises(ValueError, match='too large'):
        middle_zone(9000, 1080)
    with pytest.raises(ValueError, match='Invalid blur_strength'):
        resolve_layout_composition(
            type(
                'L',
                (),
                {
                    'foreground_treatment': 'CONTAIN',
                    'background_mode': 'SOLID',
                    'background_color': '#000000',
                    'blur_strength': 99,
                    'fit_mode': 'CROP',
                },
            )(),
        )
    with pytest.raises(ValueError, match='Invalid solid background size'):
        solid_background_filter(
            width=0,
            height=1920,
            color='#000000',
            duration_sec=1.0,
        )
    with pytest.raises(ValueError, match='duration must be positive'):
        solid_background_filter(
            width=1080,
            height=1920,
            color='000000',
            duration_sec=0,
        )
    with pytest.raises(ValueError, match='Invalid blur background size'):
        blurred_background_filter(width=1080, height=0, blur_strength=10)
    with pytest.raises(ValueError, match='Invalid blur_strength'):
        blurred_background_filter(width=1080, height=1920, blur_strength=0)


def test_invalid_clip_window_raises() -> None:
    from pathlib import Path

    from server.apps.rendering.clip_stages.trim_crop import TrimAndCropStage

    stage = TrimAndCropStage(
        source_path=Path('/in.mp4'),
        start_sec=5.0,
        end_sec=1.0,
        output_path=Path('/out.mp4'),
        layout_config=None,
    )
    with pytest.raises(ValueError, match='Invalid clip window'):
        stage._clip_duration()


def test_smart_contain_uses_composed_path() -> None:
    from pathlib import Path
    from unittest.mock import MagicMock

    from server.apps.rendering.clip_stages.trim_crop import TrimAndCropStage

    layout = MagicMock()
    layout.render_mode = 'SMART_CROP'
    layout.fit_mode = 'CROP'
    layout.foreground_treatment = 'CONTAIN'
    layout.background_mode = 'SOLID'
    layout.background_color = '#000000'
    layout.blur_strength = 20
    layout.manual_crop_x = None
    layout.manual_crop_y = None
    layout.manual_crop_w = None
    layout.manual_crop_h = None
    stage = TrimAndCropStage(
        source_path=Path('/in.mp4'),
        start_sec=0.0,
        end_sec=2.0,
        output_path=Path('/out.mp4'),
        layout_config=layout,
    )
    cmd = stage._build_command(Path('/in.mp4'))
    assert '-filter_complex' in cmd
    assert 'color=c=#000000' in cmd[cmd.index('-filter_complex') + 1]


def test_smart_square_crop_uses_detection_center() -> None:
    from pathlib import Path
    from unittest.mock import MagicMock, patch

    from server.apps.rendering.clip_stages.trim_crop import TrimAndCropStage

    layout = MagicMock()
    layout.render_mode = 'SMART_CROP'
    layout.fit_mode = 'CROP'
    layout.foreground_treatment = 'SQUARE_CROP'
    layout.background_mode = 'SOLID'
    layout.background_color = '#111111'
    layout.blur_strength = 20
    layout.manual_crop_x = None
    layout.manual_crop_y = None
    layout.manual_crop_w = None
    layout.manual_crop_h = None
    stage = TrimAndCropStage(
        source_path=Path('/in.mp4'),
        start_sec=0.0,
        end_sec=2.0,
        output_path=Path('/out.mp4'),
        layout_config=layout,
    )
    stage._speaker_svc = MagicMock()
    stage._speaker_svc.detect.return_value = MagicMock(
        crop_x=100,
        crop_y=0,
        crop_w=600,
        crop_h=1080,
    )
    with patch(
        'server.apps.rendering.clip_stages.probe.sync_ffprobe_dimensions',
        return_value=(1920, 1080),
    ):
        cmd = stage._build_command(Path('/in.mp4'))
    fc = cmd[cmd.index('-filter_complex') + 1]
    assert 'crop=600:600:100:240' in fc or 'crop=600:600' in fc
