from __future__ import annotations

from django.db import models


class RenderMode(models.TextChoices):
    SMART_CROP = "SMART_CROP", "Smart Crop (speaker-aware)"
    SPATIAL_STACK = "SPATIAL_STACK", "Spatial Stack (two regions)"
    CENTER_CROP = "CENTER_CROP", "Center Crop (static)"


class CaptionStyle(models.TextChoices):
    WORD_BY_WORD = "WORD_BY_WORD", "Word by Word (karaoke)"
    CHUNKED = "CHUNKED", "Chunked Phrases (3-4 words)"
    LOWER_THIRD = "LOWER_THIRD", "Lower Third (full segment)"
    EMOJI_ACCENT = "EMOJI_ACCENT", "Emoji Accent (chunked + emoji)"


class CaptionPosition(models.TextChoices):
    TOP = "TOP", "Top"
    CENTER = "CENTER", "Center"
    BOTTOM = "BOTTOM", "Bottom"


class CaptionAnimation(models.TextChoices):
    POP = "POP", "Pop"
    FADE = "FADE", "Fade"
    NONE = "NONE", "None"


class HookStyle(models.TextChoices):
    TITLE_CARD = "TITLE_CARD", "Title Card (black frame prepended)"
    OVERLAY_TOP = "OVERLAY_TOP", "Overlay Top (text over video)"
    OVERLAY_CENTER = "OVERLAY_CENTER", "Overlay Center (text over video)"


class TransitionStyle(models.TextChoices):
    NONE = "NONE", "None (hard cut)"
    CROSSFADE = "CROSSFADE", "Crossfade"
    FADE_BLACK = "FADE_BLACK", "Fade to Black"
    WIPE_LEFT = "WIPE_LEFT", "Wipe Left"
    WIPE_RIGHT = "WIPE_RIGHT", "Wipe Right"


class WatermarkType(models.TextChoices):
    IMAGE = "IMAGE", "Image"
    TEXT = "TEXT", "Text"


class WatermarkPosition(models.TextChoices):
    TOP_LEFT = "TOP_LEFT", "Top Left"
    TOP_RIGHT = "TOP_RIGHT", "Top Right"
    BOTTOM_LEFT = "BOTTOM_LEFT", "Bottom Left"
    BOTTOM_RIGHT = "BOTTOM_RIGHT", "Bottom Right"


class ProgressBarPosition(models.TextChoices):
    TOP = "TOP", "Top"
    BOTTOM = "BOTTOM", "Bottom"


class MediaAssetType(models.TextChoices):
    INTRO = "INTRO", "Intro"
    OUTRO = "OUTRO", "Outro"


# Maps SocialAccount.Platform values to clip render mode defaults
PLATFORM_RENDER_MODE_DEFAULTS: dict[str, str] = {
    "TIKTOK": RenderMode.SMART_CROP,
    "YOUTUBE": RenderMode.CENTER_CROP,
    "INSTAGRAM": RenderMode.SMART_CROP,
}

# Maps SocialAccount.Platform values to clip render format defaults
PLATFORM_FORMAT_DEFAULTS: dict[str, str] = {
    "TIKTOK": "VERTICAL_9_16",
    "YOUTUBE": "LANDSCAPE_16_9",
    "INSTAGRAM": "SQUARE_1_1",
}
