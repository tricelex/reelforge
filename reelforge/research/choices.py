from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class CompetitionLevel(models.TextChoices):
    LOW = "LOW", _("Low Competition")
    MEDIUM = "MEDIUM", _("Medium Competition")
    HIGH = "HIGH", _("High Competition")


class ApprovalSource(models.TextChoices):
    MANUAL = "MANUAL", _("Manual Approval")
    AUTO = "AUTO", _("Auto-Approved (Delay)")
    AGENT = "AGENT", _("Agent-Approved")


class TrendDirection(models.TextChoices):
    RISING = "RISING", _("Rising")
    STABLE = "STABLE", _("Stable")
    DECLINING = "DECLINING", _("Declining")


class ResearchTrigger(models.TextChoices):
    SCHEDULED = "SCHEDULED", _("Scheduled Auto-Research")
    MANUAL = "MANUAL", _("Manual Trigger")
    AUTO = "AUTO", _("Auto-Triggered (Gap Analysis)")
