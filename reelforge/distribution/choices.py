from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class YouTubePrivacy(models.TextChoices):
    PUBLIC = "PUBLIC", _("Public")
    PRIVATE = "PRIVATE", _("Private")
    UNLISTED = "UNLISTED", _("Unlisted")


class UploadStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    UPLOADING = "UPLOADING", _("Uploading")
    PROCESSING = "PROCESSING", _("Processing")
    COMPLETED = "COMPLETED", _("Completed")
    FAILED = "FAILED", _("Failed")


class PerformanceClass(models.TextChoices):
    VIRAL = "VIRAL", _("Viral (>100k in 7d)")
    ABOVE_AVG = "ABOVE_AVG", _("Above Average")
    AVERAGE = "AVERAGE", _("Average")
    UNDERPERFORM = "UNDERPERFORM", _("Underperforming")
