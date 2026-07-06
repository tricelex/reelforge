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
    'KARAOKE_HIGHLIGHT',
]

# HookStyle.values
HookStyleLiteral = Literal['TITLE_CARD', 'OVERLAY_TOP', 'OVERLAY_CENTER']

# TransitionStyle.values
TransitionStyleLiteral = Literal[
    'NONE',
    'CROSSFADE',
    'FADE_BLACK',
    'FADE_WHITE',
    'SLIDE_LEFT',
    'SLIDE_RIGHT',
    'SLIDE_UP',
    'SLIDE_DOWN',
    'WIPE_LEFT',
    'WIPE_RIGHT',
    'ZOOM_IN',
    'CUSTOM_ASSET',
]

# WatermarkType.values
WatermarkTypeLiteral = Literal['IMAGE', 'TEXT']

# WatermarkPosition.values
WatermarkPositionLiteral = Literal[
    'TOP_LEFT',
    'TOP_RIGHT',
    'BOTTOM_LEFT',
    'BOTTOM_RIGHT',
    'CENTER',
    'TILED',
]

# ProgressBarPosition.values
ProgressBarPositionLiteral = Literal['TOP', 'BOTTOM']

# OverlayType.values
OverlayTypeLiteral = Literal['TEXT', 'IMAGE', 'VIDEO']

# CaptionFont.values
CaptionFontLiteral = Literal[
    'MONTSERRAT_BOLD',
    'POPPINS_BOLD',
    'INTER_BOLD',
    'ROBOTO_BOLD',
    'OSWALD_BOLD',
    'BEBAS_NEUE',
    'ANTON',
    'ARCHIVO_BLACK',
    'BANGERS',
    'PERMANENT_MARKER',
    'CAVEAT_BOLD',
    'LOBSTER',
    'PLAYFAIR_DISPLAY_BOLD',
    'RIGHTEOUS',
    'LUCKIEST_GUY',
    'PACIFICO',
]

# OverlayAnimation.values
OverlayAnimationLiteral = Literal[
    'NONE',
    'FADE',
    'POP',
    'SLIDE_LEFT',
    'SLIDE_RIGHT',
    'SLIDE_UP',
    'SLIDE_DOWN',
]

# ColorFilterPreset.values
ColorFilterPresetLiteral = Literal[
    'NONE',
    'VIVID',
    'MOODY',
    'WARM',
    'COOL',
    'BLACK_WHITE',
    'VINTAGE',
]

# FitMode.values
FitModeLiteral = Literal['CROP', 'BLUR_FILL']

# OverlayShape.values
OverlayShapeLiteral = Literal['RECTANGLE', 'CIRCLE', 'ROUNDED']

# Pixel coords relative to source video frame (origin top-left).
_CROP_COORD_DESC = (
    'Pixel coordinate relative to source video (source_width x source_height), '
    'origin top-left.'
)
