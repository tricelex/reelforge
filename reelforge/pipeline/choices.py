from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class PipelineStatus(models.TextChoices):
    INITIALIZING = "INITIALIZING", _("Initializing")
    RESEARCHING = "RESEARCHING", _("Researching Topics")
    SCRIPTING = "SCRIPTING", _("Writing Script")
    AWAITING_APPROVAL = "AWAITING_APPROVAL", _("Awaiting Approval")
    SCENE_BREAKDOWN = "SCENE_BREAKDOWN", _("Breaking Down Scenes")
    GENERATING_ASSETS = "GENERATING_ASSETS", _("Generating Assets")
    AUDIO_MIX = "AUDIO_MIX", _("Mixing Audio")
    CLIP_GENERATION = "CLIP_GENERATION", _("Generating Video Clips")
    RENDERING = "RENDERING", _("Rendering Video")
    QA = "QA", _("Quality Assurance")
    UPLOADING = "UPLOADING", _("Uploading to YouTube")
    PUBLISHED = "PUBLISHED", _("Published")
    FAILED = "FAILED", _("Failed")
    PAUSED = "PAUSED", _("Paused")


class EventType(models.TextChoices):
    INFO = "INFO", _("Information")
    SUCCESS = "SUCCESS", _("Success")
    WARNING = "WARNING", _("Warning")
    ERROR = "ERROR", _("Error")
    RETRY = "RETRY", _("Retry Attempt")
    MANUAL = "MANUAL", _("Manual Intervention")
