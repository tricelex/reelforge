"""Literal types must match TextChoices values."""

from typing import get_args

from server.apps.channel_research.logic.constants import (
    ChannelResearchKind,
    ChannelResearchStatus,
    DeepAnalysisStatus,
    VisualMedium,
)
from server.apps.channel_research.logic.types import (
    ChannelResearchKindLiteral,
    ChannelResearchStatusLiteral,
    DeepAnalysisStatusLiteral,
    VisualMediumLiteral,
)


def test_status_literal_matches_choices() -> None:
    assert set(get_args(ChannelResearchStatusLiteral)) == set(
        ChannelResearchStatus.values,
    )


def test_kind_literal_matches_choices() -> None:
    assert set(get_args(ChannelResearchKindLiteral)) == set(
        ChannelResearchKind.values,
    )


def test_visual_medium_literal_matches_choices() -> None:
    assert set(get_args(VisualMediumLiteral)) == set(VisualMedium.values)


def test_deep_analysis_status_literal_matches_choices() -> None:
    assert set(get_args(DeepAnalysisStatusLiteral)) == set(
        DeepAnalysisStatus.values,
    )
