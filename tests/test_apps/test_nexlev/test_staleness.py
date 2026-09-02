"""Tests for the NexLev section staleness helper."""

from datetime import timedelta

from django.utils import timezone

from server.apps.nexlev.logic.staleness import is_stale


def test_is_stale_when_never_fetched() -> None:
    assert is_stale(None, window=timedelta(days=7)) is True


def test_is_stale_when_older_than_window() -> None:
    fetched_at = timezone.now() - timedelta(days=8)
    assert is_stale(fetched_at, window=timedelta(days=7)) is True


def test_is_stale_when_within_window() -> None:
    fetched_at = timezone.now() - timedelta(days=1)
    assert is_stale(fetched_at, window=timedelta(days=7)) is False
