from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class AssetStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    GENERATING = "GENERATING", _("Generating")
    COMPLETED = "COMPLETED", _("Completed")
    FAILED = "FAILED", _("Failed")


class AnimationType(models.TextChoices):
    NONE = "NONE", _("No Animation")
    KEN_BURNS = "KEN_BURNS", _("Ken Burns (Zoom + Pan)")
    ZOOM = "ZOOM", _("Zoom Only")
    PAN = "PAN", _("Pan Only")
    FADE = "FADE", _("Fade In/Out")
