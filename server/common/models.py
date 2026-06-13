"""Abstract base models shared across all apps."""

import uuid

from django.db import models


class UUIDModel(models.Model):
    """Abstract model that uses a UUID primary key instead of auto-int."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        """Meta options for UUIDModel."""

        abstract = True


class TimeStampedModel(models.Model):
    """Abstract model that records creation and last-modification times."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Meta options for TimeStampedModel."""

        abstract = True
