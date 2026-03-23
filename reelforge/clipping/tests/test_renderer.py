from __future__ import annotations

from pathlib import Path

import pytest

from reelforge.services.media.clip_renderer import ClipRenderConfig
from reelforge.services.media.clip_renderer import ClipRenderer


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


def test_clip_renderer_build_ffmpeg_args_contains_required_flags() -> None:
    config = ClipRenderConfig(
        source_path=Path("/tmp/source.mp4"),
        output_path=Path("/tmp/output.mp4"),
        start_sec=0.0,
        end_sec=60.0,
        include_captions=False,
        include_title_card=False,
        include_branding=False,
    )
    renderer = ClipRenderer(config)
    args = renderer._build_ffmpeg_command()

    # Must include timing
    assert "-ss" in args
    assert "0.0" in args
    assert "-to" in args
    assert "60.0" in args
    # Must include output codec settings
    assert "libx264" in args
    assert "aac" in args
    assert "faststart" in args


def test_clip_renderer_output_path_used_correctly() -> None:
    config = ClipRenderConfig(
        source_path=Path("/tmp/source.mp4"),
        output_path=Path("/tmp/my_render.mp4"),
        start_sec=30.0,
        end_sec=90.0,
    )
    renderer = ClipRenderer(config)
    args = renderer._build_ffmpeg_command()
    assert "/tmp/my_render.mp4" in args
