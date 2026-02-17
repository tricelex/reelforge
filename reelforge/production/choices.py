from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class RenderEngine(models.TextChoices):
    REMOTION = "REMOTION", _("Remotion (React)")
    MOVIEPY = "MOVIEPY", _("MoviePy (Python)")
    FFMPEG = "FFMPEG", _("FFmpeg Direct")
    PICTORY = "PICTORY", _("Pictory.ai (External)")
