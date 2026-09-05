"""Tests for the canonical transition-style vocabulary."""

from server.common.transition_styles import (
    HARD_CUT,
    VALID_TRANSITION_STYLES,
    XFADE_TRANSITION_STYLES,
)


def test_hard_cut_is_not_an_xfade_style() -> None:
    """hard_cut skips rendering's xfade table entirely (fast concat path)."""
    assert HARD_CUT not in XFADE_TRANSITION_STYLES


def test_valid_transition_styles_includes_hard_cut_and_xfade_styles() -> None:
    assert XFADE_TRANSITION_STYLES | {HARD_CUT} == VALID_TRANSITION_STYLES
