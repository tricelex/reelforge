"""Ensure OpenAPI Literal types stay aligned with Django TextChoices."""

from typing import get_args

from server.apps.clips.logic.constants import (
    CandidateStatus,
    CaptionAnimation,
    CaptionPosition,
    CaptionStyle,
    HookStyle,
    OverlayType,
    ProgressBarPosition,
    RenderFormat,
    RenderMode,
    TransitionStyle,
    WatermarkPosition,
    WatermarkType,
)
from server.apps.clips.logic.types import (
    CandidateStatusLiteral,
    CaptionAnimationLiteral,
    CaptionPositionLiteral,
    CaptionStyleLiteral,
    HookStyleLiteral,
    OverlayTypeLiteral,
    ProgressBarPositionLiteral,
    RenderFormatLiteral,
    RenderModeLiteral,
    TransitionStyleLiteral,
    WatermarkPositionLiteral,
    WatermarkTypeLiteral,
)


def test_render_mode_literal_matches_choices() -> None:
    assert set(get_args(RenderModeLiteral)) == set(RenderMode.values)


def test_render_format_literal_matches_choices() -> None:
    assert set(get_args(RenderFormatLiteral)) == set(RenderFormat.values)


def test_candidate_status_literal_matches_choices() -> None:
    assert set(get_args(CandidateStatusLiteral)) == set(CandidateStatus.values)


def test_caption_position_literal_matches_choices() -> None:
    assert set(get_args(CaptionPositionLiteral)) == set(CaptionPosition.values)


def test_caption_animation_literal_matches_choices() -> None:
    assert set(get_args(CaptionAnimationLiteral)) == set(CaptionAnimation.values)


def test_caption_style_literal_matches_choices() -> None:
    assert set(get_args(CaptionStyleLiteral)) == set(CaptionStyle.values)


def test_hook_style_literal_matches_choices() -> None:
    assert set(get_args(HookStyleLiteral)) == set(HookStyle.values)


def test_transition_style_literal_matches_choices() -> None:
    assert set(get_args(TransitionStyleLiteral)) == set(TransitionStyle.values)


def test_watermark_type_literal_matches_choices() -> None:
    assert set(get_args(WatermarkTypeLiteral)) == set(WatermarkType.values)


def test_watermark_position_literal_matches_choices() -> None:
    assert set(get_args(WatermarkPositionLiteral)) == set(WatermarkPosition.values)


def test_progress_bar_position_literal_matches_choices() -> None:
    assert set(get_args(ProgressBarPositionLiteral)) == set(
        ProgressBarPosition.values,
    )


def test_overlay_type_literal_matches_choices() -> None:
    assert set(get_args(OverlayTypeLiteral)) == set(OverlayType.values)
