"""Staleness check for one persisted NexLev section timestamp."""

from datetime import datetime, timedelta

from django.utils import timezone


def is_stale(fetched_at: datetime | None, *, window: timedelta) -> bool:
    """True when the section was never fetched or is older than window."""
    if fetched_at is None:
        return True
    return timezone.now() - fetched_at > window
