"""OpenAPI-facing literal types derived from clips TextChoices.

Wire values must match Django TextChoices in constants.py (enforced in tests).
"""

from typing import Literal

# RenderMode.values
RenderModeLiteral = Literal['SMART_CROP', 'SPATIAL_STACK', 'CENTER_CROP']

# RenderFormat.values
RenderFormatLiteral = Literal[
    'VERTICAL_9_16',
    'LANDSCAPE_16_9',
    'SQUARE_1_1',
]

# CandidateStatus.values
CandidateStatusLiteral = Literal[
    'PROPOSED',
    'APPROVED',
    'REJECTED',
    'RENDERING',
    'RENDERED',
    'DISTRIBUTING',
    'DISTRIBUTED',
]

# CaptionPosition.values
CaptionPositionLiteral = Literal['TOP', 'CENTER', 'BOTTOM']

# CaptionAnimation.values
CaptionAnimationLiteral = Literal['POP', 'FADE', 'NONE']

# CaptionStyle.values
CaptionStyleLiteral = Literal[
    'WORD_BY_WORD',
    'CHUNKED',
    'LOWER_THIRD',
    'EMOJI_ACCENT',
]

# HookStyle.values
HookStyleLiteral = Literal['TITLE_CARD', 'OVERLAY_TOP', 'OVERLAY_CENTER']

# TransitionStyle.values
TransitionStyleLiteral = Literal['NONE', 'CROSSFADE', 'FADE_BLACK']

# WatermarkType.values
WatermarkTypeLiteral = Literal['IMAGE', 'TEXT']

# WatermarkPosition.values
WatermarkPositionLiteral = Literal[
    'TOP_LEFT',
    'TOP_RIGHT',
    'BOTTOM_LEFT',
    'BOTTOM_RIGHT',
]

# ProgressBarPosition.values
ProgressBarPositionLiteral = Literal['TOP', 'BOTTOM']

# OverlayType.values
OverlayTypeLiteral = Literal['TEXT', 'IMAGE']

# Pixel coords relative to source video frame (origin top-left).
_CROP_COORD_DESC = (
    'Pixel coordinate relative to source video (source_width x source_height), '
    'origin top-left.'
)
