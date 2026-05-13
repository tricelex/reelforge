from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

from reelforge.services.media.clip_renderer import ClipRenderConfig
from reelforge.services.media.clip_renderer import ClipRenderer
from reelforge.services.media.speaker_detection import SpeakerCropResult


def _make_config(**kwargs) -> ClipRenderConfig:
    defaults = {
        "source_path": Path("/tmp/source.mp4"),
        "output_path": Path("/tmp/output.mp4"),
        "start_sec": 0.0,
        "end_sec": 60.0,
        "include_captions": False,
        "include_title_card": False,
        "include_branding": False,
    }
    defaults.update(kwargs)
    return ClipRenderConfig(**defaults)


def _make_layout_config(render_mode: str, **extra) -> MagicMock:
    from reelforge.clipping.models import ClipLayoutConfig

    lc = MagicMock(spec=ClipLayoutConfig)
    lc.render_mode = render_mode
    lc.has_manual_smart_crop = False
    lc.has_spatial_regions = False
    for k, v in extra.items():
        setattr(lc, k, v)
    return lc


def test_clip_render_config_defaults() -> None:
    config = ClipRenderConfig(
        source_path=Path("/tmp/source.mp4"),
        output_path=Path("/tmp/output.mp4"),
        start_sec=60.0,
        end_sec=120.0,
    )
    assert config.width == 1080
    assert config.height == 1920
    assert config.fps == 30
    assert config.include_captions is True
    assert config.include_title_card is True
    assert config.layout_config is None


def test_clip_renderer_has_last_speaker_crop_result_attribute() -> None:
    renderer = ClipRenderer(_make_config())
    assert renderer.last_speaker_crop_result is None


# --- CENTER_CROP ---

def test_center_crop_command_contains_required_flags() -> None:
    from reelforge.clipping.models import ClipLayoutConfig

    config = _make_config(layout_config=_make_layout_config(ClipLayoutConfig.RenderMode.CENTER_CROP))
    renderer = ClipRenderer(config)
    args = renderer._build_ffmpeg_command()

    assert "-ss" in args
    assert "0.0" in args
    assert "-to" in args
    assert "60.0" in args
    assert "libx264" in args
    assert "aac" in args
    assert "faststart" in args
    assert "ih*9/16:ih" in " ".join(args)


def test_no_layout_config_falls_back_to_center_crop() -> None:
    config = _make_config(layout_config=None)
    renderer = ClipRenderer(config)
    args = renderer._build_ffmpeg_command()
    assert "ih*9/16:ih" in " ".join(args)


def test_clip_renderer_output_path_used_correctly() -> None:
    config = _make_config(output_path=Path("/tmp/my_render.mp4"))
    renderer = ClipRenderer(config)
    args = renderer._build_ffmpeg_command()
    assert "/tmp/my_render.mp4" in args


# --- SMART_CROP ---

def test_smart_crop_auto_detect_calls_speaker_detection_service() -> None:
    from reelforge.clipping.models import ClipLayoutConfig

    lc = _make_layout_config(ClipLayoutConfig.RenderMode.SMART_CROP, has_manual_smart_crop=False)
    config = _make_config(layout_config=lc)
    renderer = ClipRenderer(config)

    mock_result = SpeakerCropResult(crop_x=100, crop_w=405, crop_h=720, confidence=0.8, face_detected=True)
    with patch(
        "reelforge.services.media.clip_renderer.SpeakerDetectionService.detect",
        return_value=mock_result,
    ):
        args = renderer._build_ffmpeg_command()

    assert renderer.last_speaker_crop_result is mock_result
    assert "crop=405:720:100:0" in " ".join(args)


def test_smart_crop_manual_override_skips_detection() -> None:
    from reelforge.clipping.models import ClipLayoutConfig

    lc = _make_layout_config(
        ClipLayoutConfig.RenderMode.SMART_CROP,
        has_manual_smart_crop=True,
        manual_crop_x=200,
        manual_crop_w=405,
        manual_crop_h=720,
    )
    config = _make_config(layout_config=lc)
    renderer = ClipRenderer(config)

    with patch(
        "reelforge.services.media.clip_renderer.SpeakerDetectionService.detect"
    ) as mock_detect:
        args = renderer._build_ffmpeg_command()

    mock_detect.assert_not_called()
    assert renderer.last_speaker_crop_result is None
    assert "crop=405:720:200:0" in " ".join(args)


# --- SPATIAL_STACK ---

def test_spatial_stack_uses_filter_complex_with_vstack() -> None:
    from reelforge.clipping.models import ClipLayoutConfig

    lc = _make_layout_config(
        ClipLayoutConfig.RenderMode.SPATIAL_STACK,
        has_spatial_regions=True,
        region_a_x=0, region_a_y=0, region_a_w=400, region_a_h=300,
        region_b_x=880, region_b_y=420, region_b_w=400, region_b_h=300,
        stack_ratio=0.6,
        id="test-uuid",
    )
    config = _make_config(layout_config=lc)
    renderer = ClipRenderer(config)
    args = renderer._build_ffmpeg_command()

    assert "-filter_complex" in args
    fc_idx = args.index("-filter_complex")
    filter_str = args[fc_idx + 1]
    assert "vstack" in filter_str
    assert "crop=400:300:0:0" in filter_str     # region A
    assert "crop=400:300:880:420" in filter_str  # region B


def test_spatial_stack_output_dimensions_respect_stack_ratio() -> None:
    from reelforge.clipping.models import ClipLayoutConfig

    lc = _make_layout_config(
        ClipLayoutConfig.RenderMode.SPATIAL_STACK,
        has_spatial_regions=True,
        region_a_x=0, region_a_y=0, region_a_w=640, region_a_h=360,
        region_b_x=0, region_b_y=360, region_b_w=640, region_b_h=360,
        stack_ratio=0.5,
        id="test-uuid",
    )
    config = _make_config(layout_config=lc)
    renderer = ClipRenderer(config)
    args = renderer._build_ffmpeg_command()

    fc_idx = args.index("-filter_complex")
    filter_str = args[fc_idx + 1]
    # out_h=1920, stack_ratio=0.5 → a_out_h=960, b_out_h=960
    assert "scale=1080:960" in filter_str


def test_spatial_stack_without_regions_falls_back_to_center_crop() -> None:
    from reelforge.clipping.models import ClipLayoutConfig

    lc = _make_layout_config(
        ClipLayoutConfig.RenderMode.SPATIAL_STACK,
        has_spatial_regions=False,
        id="test-uuid",
    )
    config = _make_config(layout_config=lc)
    renderer = ClipRenderer(config)
    args = renderer._build_ffmpeg_command()

    # Should fall back to center crop
    assert "ih*9/16:ih" in " ".join(args)
    assert "-filter_complex" not in args
