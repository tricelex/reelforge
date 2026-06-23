from django.db import models


class IdeaStatus(models.TextChoices):
    """Lifecycle status of a topic idea in the backlog."""

    BACKLOG = 'BACKLOG', 'Backlog'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'
    PROMOTED = 'PROMOTED', 'Promoted'
