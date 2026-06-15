from django.db import models


class RenderMode(models.TextChoices):
    """Rendering layout mode for a clip."""

    SMART_CROP = 'SMART_CROP', 'Smart Crop (speaker-aware)'
    SPATIAL_STACK = 'SPATIAL_STACK', 'Spatial Stack (two regions)'
    CENTER_CROP = 'CENTER_CROP', 'Center Crop (static)'


class RenderFormat(models.TextChoices):
    """Output aspect ratio / format for a rendered clip."""

    VERTICAL_9_16 = 'VERTICAL_9_16', 'Vertical 9:16'
    LANDSCAPE_16_9 = 'LANDSCAPE_16_9', 'Landscape 16:9'
    SQUARE_1_1 = 'SQUARE_1_1', 'Square 1:1'


class CandidateStatus(models.TextChoices):
    """Lifecycle status of a clip candidate."""

    PROPOSED = 'PROPOSED', 'Proposed'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'
    RENDERING = 'RENDERING', 'Rendering'
    RENDERED = 'RENDERED', 'Rendered'
    DISTRIBUTING = 'DISTRIBUTING', 'Distributing'
    DISTRIBUTED = 'DISTRIBUTED', 'Distributed'


class CaptionStyle(models.TextChoices):
    """Visual style used for rendering captions."""

    WORD_BY_WORD = 'WORD_BY_WORD', 'Word by Word (karaoke)'
    CHUNKED = 'CHUNKED', 'Chunked Phrases (3-4 words)'
    LOWER_THIRD = 'LOWER_THIRD', 'Lower Third (full segment)'
    EMOJI_ACCENT = 'EMOJI_ACCENT', 'Emoji Accent (chunked + emoji)'


class CaptionPosition(models.TextChoices):
    """Vertical placement of captions on the frame."""

    TOP = 'TOP', 'Top'
    CENTER = 'CENTER', 'Center'
    BOTTOM = 'BOTTOM', 'Bottom'


class CaptionAnimation(models.TextChoices):
    """Entrance animation applied to each caption unit."""

    POP = 'POP', 'Pop'
    FADE = 'FADE', 'Fade'
    NONE = 'NONE', 'None'


class HookStyle(models.TextChoices):
    """Style of the opening hook overlay."""

    TITLE_CARD = 'TITLE_CARD', 'Title Card'
    OVERLAY_TOP = 'OVERLAY_TOP', 'Overlay Top'
    OVERLAY_CENTER = 'OVERLAY_CENTER', 'Overlay Center'


class TransitionStyle(models.TextChoices):
    """Transition applied between clip segments."""

    NONE = 'NONE', 'None (hard cut)'
    CROSSFADE = 'CROSSFADE', 'Crossfade'
    FADE_BLACK = 'FADE_BLACK', 'Fade to Black'


class WatermarkType(models.TextChoices):
    """Type of watermark overlaid on the clip."""

    IMAGE = 'IMAGE', 'Image'
    TEXT = 'TEXT', 'Text'


class WatermarkPosition(models.TextChoices):
    """Corner position of the watermark."""

    TOP_LEFT = 'TOP_LEFT', 'Top Left'
    TOP_RIGHT = 'TOP_RIGHT', 'Top Right'
    BOTTOM_LEFT = 'BOTTOM_LEFT', 'Bottom Left'
    BOTTOM_RIGHT = 'BOTTOM_RIGHT', 'Bottom Right'


class ProgressBarPosition(models.TextChoices):
    """Edge position of the progress bar."""

    TOP = 'TOP', 'Top'
    BOTTOM = 'BOTTOM', 'Bottom'


class PostStatus(models.TextChoices):
    """Distribution post lifecycle status."""

    PENDING = 'PENDING', 'Pending'
    POSTING = 'POSTING', 'Posting'
    POSTED = 'POSTED', 'Posted'
    FAILED = 'FAILED', 'Failed'


class OverlayType(models.TextChoices):
    """Type of a timed overlay on a clip."""

    TEXT = 'TEXT', 'Text'
    IMAGE = 'IMAGE', 'Image'
