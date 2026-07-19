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


#: Full-quality output dimensions (width, height) per render format.
RENDER_FORMAT_DIMENSIONS: dict[str, tuple[int, int]] = {
    RenderFormat.VERTICAL_9_16: (1080, 1920),
    RenderFormat.LANDSCAPE_16_9: (1920, 1080),
    RenderFormat.SQUARE_1_1: (1080, 1080),
}


def render_format_dimensions(render_format: str) -> tuple[int, int]:
    """Return (width, height) for a render format; default 9:16 vertical."""
    return RENDER_FORMAT_DIMENSIONS.get(
        render_format,
        RENDER_FORMAT_DIMENSIONS[RenderFormat.VERTICAL_9_16],
    )


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
    KARAOKE_HIGHLIGHT = 'KARAOKE_HIGHLIGHT', 'Karaoke Highlight'


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
    FADE_WHITE = 'FADE_WHITE', 'Fade to White'
    SLIDE_LEFT = 'SLIDE_LEFT', 'Slide Left'
    SLIDE_RIGHT = 'SLIDE_RIGHT', 'Slide Right'
    SLIDE_UP = 'SLIDE_UP', 'Slide Up'
    SLIDE_DOWN = 'SLIDE_DOWN', 'Slide Down'
    WIPE_LEFT = 'WIPE_LEFT', 'Wipe Left'
    WIPE_RIGHT = 'WIPE_RIGHT', 'Wipe Right'
    ZOOM_IN = 'ZOOM_IN', 'Zoom In'
    CUSTOM_ASSET = 'CUSTOM_ASSET', 'Custom Transition Video'


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
    CENTER = 'CENTER', 'Center'
    TILED = 'TILED', 'Tiled'


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


class CampaignStatus(models.TextChoices):
    """Lifecycle status of a clip export campaign."""

    DRAFT = 'DRAFT', 'Draft'
    ACTIVE = 'ACTIVE', 'Active'
    COMPLETED = 'COMPLETED', 'Completed'


class OverlayType(models.TextChoices):
    """Type of a timed overlay on a clip."""

    TEXT = 'TEXT', 'Text'
    IMAGE = 'IMAGE', 'Image'
    VIDEO = 'VIDEO', 'Video'


class CaptionFont(models.TextChoices):
    """Curated font palette, shared by captions, hook, watermark, overlays."""

    MONTSERRAT_BOLD = 'MONTSERRAT_BOLD', 'Montserrat Bold'
    POPPINS_BOLD = 'POPPINS_BOLD', 'Poppins Bold'
    INTER_BOLD = 'INTER_BOLD', 'Inter Bold'
    ROBOTO_BOLD = 'ROBOTO_BOLD', 'Roboto Bold'
    OSWALD_BOLD = 'OSWALD_BOLD', 'Oswald Bold'
    BEBAS_NEUE = 'BEBAS_NEUE', 'Bebas Neue'
    ANTON = 'ANTON', 'Anton'
    ARCHIVO_BLACK = 'ARCHIVO_BLACK', 'Archivo Black'
    BANGERS = 'BANGERS', 'Bangers'
    PERMANENT_MARKER = 'PERMANENT_MARKER', 'Permanent Marker'
    CAVEAT_BOLD = 'CAVEAT_BOLD', 'Caveat Bold'
    LOBSTER = 'LOBSTER', 'Lobster'
    PLAYFAIR_DISPLAY_BOLD = 'PLAYFAIR_DISPLAY_BOLD', 'Playfair Display Bold'
    RIGHTEOUS = 'RIGHTEOUS', 'Righteous'
    LUCKIEST_GUY = 'LUCKIEST_GUY', 'Luckiest Guy'
    PACIFICO = 'PACIFICO', 'Pacifico'


class OverlayAnimation(models.TextChoices):
    """Entrance/exit animation for a timed overlay or the hook."""

    NONE = 'NONE', 'None'
    FADE = 'FADE', 'Fade'
    POP = 'POP', 'Pop'
    SLIDE_LEFT = 'SLIDE_LEFT', 'Slide Left'
    SLIDE_RIGHT = 'SLIDE_RIGHT', 'Slide Right'
    SLIDE_UP = 'SLIDE_UP', 'Slide Up'
    SLIDE_DOWN = 'SLIDE_DOWN', 'Slide Down'


class ColorFilterPreset(models.TextChoices):
    """Preset color-grade look applied before manual adjustments."""

    NONE = 'NONE', 'None'
    VIVID = 'VIVID', 'Vivid'
    MOODY = 'MOODY', 'Moody'
    WARM = 'WARM', 'Warm'
    COOL = 'COOL', 'Cool'
    BLACK_WHITE = 'BLACK_WHITE', 'Black & White'
    VINTAGE = 'VINTAGE', 'Vintage'


class FitMode(models.TextChoices):
    """How the source video fills a mismatched target aspect ratio."""

    CROP = 'CROP', 'Crop'
    BLUR_FILL = 'BLUR_FILL', 'Blurred Background Fill'


class OverlayShape(models.TextChoices):
    """Mask shape for image/video overlays."""

    RECTANGLE = 'RECTANGLE', 'Rectangle'
    CIRCLE = 'CIRCLE', 'Circle'
    ROUNDED = 'ROUNDED', 'Rounded Rectangle'


class ClipSourceStatus(models.TextChoices):
    """Ingest lifecycle for a clip source."""

    INGESTING = 'INGESTING', 'Ingesting'
    READY = 'READY', 'Ready'
    FAILED = 'FAILED', 'Failed'


class ClipSourceType(models.TextChoices):
    """Origin of a clip source video."""

    YOUTUBE = 'youtube', 'YouTube'
    RSS = 'rss', 'RSS'
    UPLOAD = 'upload', 'Upload'


class ClipGenre(models.TextChoices):
    """Content genre hint for clip discovery."""

    AUTO = 'auto', 'Auto'
    PODCAST = 'podcast', 'Podcast'
    QA = 'q_and_a', 'Q&A'
    COMMENTARY = 'commentary', 'Commentary'
    MARKETING = 'marketing', 'Marketing'
    WEBINAR = 'webinar', 'Webinar'
    MOTIVATIONAL = 'motivational', 'Motivational speech'


class ClipLengthBucket(models.TextChoices):
    """Preferred output duration bucket for discovered clips."""

    AUTO = 'auto', 'Auto (0m-3m)'
    UNDER_30 = 'under_30', '<30s'
    FROM_30_TO_59 = '30_59', '30s–59s'
    FROM_60_TO_89 = '60_89', '60s–89s'
    FROM_90_TO_180 = '90_180', '90s–3m'
    FROM_180_TO_300 = '180_300', '3m–5m'
    FROM_300_TO_600 = '300_600', '5m–10m'
    CUSTOM = 'custom', 'Custom range'


#: Inclusive (min_sec, max_sec) bounds per duration bucket.
CLIP_LENGTH_BOUNDS: dict[str, tuple[float, float]] = {
    ClipLengthBucket.AUTO: (15.0, 180.0),
    ClipLengthBucket.UNDER_30: (8.0, 29.999),
    ClipLengthBucket.FROM_30_TO_59: (30.0, 59.999),
    ClipLengthBucket.FROM_60_TO_89: (60.0, 89.999),
    ClipLengthBucket.FROM_90_TO_180: (90.0, 180.0),
    ClipLengthBucket.FROM_180_TO_300: (180.0, 300.0),
    ClipLengthBucket.FROM_300_TO_600: (300.0, 600.0),
}


#: Deterministic virality weights (must sum to 1.0).
VIRALITY_WEIGHTS: dict[str, float] = {
    'hook': 0.30,
    'flow': 0.25,
    'value': 0.30,
    'trend': 0.15,
}
VIRALITY_SCORE_VERSION = 'v1'


def score_to_letter_grade(score: float) -> str:
    """Map a 0-100 score to a letter grade used in the results UI."""
    clamped = max(0.0, min(100.0, float(score)))
    if clamped >= 97:
        return 'A+'
    if clamped >= 93:
        return 'A'
    if clamped >= 90:
        return 'A-'
    if clamped >= 87:
        return 'B+'
    if clamped >= 83:
        return 'B'
    if clamped >= 80:
        return 'B-'
    if clamped >= 77:
        return 'C+'
    if clamped >= 73:
        return 'C'
    if clamped >= 70:
        return 'C-'
    if clamped >= 60:
        return 'D'
    return 'F'


def compute_virality_score(
    *,
    hook_score: float,
    flow_score: float,
    value_score: float,
    trend_score: float,
) -> float:
    """Compute overall virality from weighted factor scores."""
    total = (
        hook_score * VIRALITY_WEIGHTS['hook']
        + flow_score * VIRALITY_WEIGHTS['flow']
        + value_score * VIRALITY_WEIGHTS['value']
        + trend_score * VIRALITY_WEIGHTS['trend']
    )
    return round(max(0.0, min(100.0, total)), 2)
