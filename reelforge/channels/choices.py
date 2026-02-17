from django.db import models


class ChannelStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    PAUSED = "PAUSED", "Paused"
    ARCHIVED = "ARCHIVED", "Archived"
    SETUP = "SETUP", "Setup in Progress"


class NicheCategory(models.TextChoices):
    FINANCE = "FINANCE", "Personal Finance"
    HEALTH = "HEALTH", "Health & Wellness"
    PRODUCTIVITY = "PRODUCTIVITY", "Productivity"
    STOICISM = "STOICISM", "Stoicism / Philosophy"
    TECH = "TECH", "Technology"
    BUSINESS = "BUSINESS", "Business"
    TRUE_CRIME = "TRUE_CRIME", "True Crime"
    HISTORY = "HISTORY", "History"
    MOTIVATION = "MOTIVATION", "Motivation"
    CUSTOM = "CUSTOM", "Custom Niche"
