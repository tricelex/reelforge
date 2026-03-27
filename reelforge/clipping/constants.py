from __future__ import annotations

from django.db import models


class RenderMode(models.TextChoices):
    SMART_CROP = "SMART_CROP", "Smart Crop (speaker-aware)"
    SPATIAL_STACK = "SPATIAL_STACK", "Spatial Stack (two regions)"
    CENTER_CROP = "CENTER_CROP", "Center Crop (static)"
