"""OpenAPI-facing literal types for channel research.

Wire values must match TextChoices in constants.py (enforced in tests).
"""

from typing import Literal

ChannelResearchStatusLiteral = Literal[
    'PENDING',
    'QUEUED',
    'RUNNING',
    'SUCCEEDED',
    'FAILED',
]

ChannelResearchKindLiteral = Literal['LONGFORM', 'SHORTS', 'CLIPPING']

VisualMediumLiteral = Literal[
    '2d_animation',
    '3d_cgi',
    'motion_graphics',
    'photoreal',
    'live_action_stock',
    'mixed',
]

RecommendedModeLiteral = Literal['same_niche', 'bent']
