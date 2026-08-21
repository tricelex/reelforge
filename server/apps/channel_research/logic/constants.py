from django.db import models


class ChannelResearchStatus(models.TextChoices):
    """Lifecycle of a channel research job."""

    PENDING = 'PENDING', 'Pending'
    QUEUED = 'QUEUED', 'Queued'
    RUNNING = 'RUNNING', 'Running'
    SUCCEEDED = 'SUCCEEDED', 'Succeeded'
    FAILED = 'FAILED', 'Failed'


class ChannelResearchKind(models.TextChoices):
    """Content kind the resulting ChannelSpec should target."""

    LONGFORM = 'LONGFORM', 'Long-form'
    SHORTS = 'SHORTS', 'Shorts'
    CLIPPING = 'CLIPPING', 'Clipping'


class VisualMedium(models.TextChoices):
    """Source-channel visual medium classified during research."""

    TWO_D_ANIMATION = '2d_animation', '2D animation'
    THREE_D_CGI = '3d_cgi', '3D CGI'
    MOTION_GRAPHICS = 'motion_graphics', 'Motion graphics'
    PHOTOREAL = 'photoreal', 'Photoreal'
    LIVE_ACTION_STOCK = 'live_action_stock', 'Live-action stock'
    MIXED = 'mixed', 'Mixed'
