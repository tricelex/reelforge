"""Tests for server/common/scheduler.py."""

from taskiq import TaskiqScheduler

from server.common.scheduler import scheduler


def test_scheduler_is_taskiq_scheduler() -> None:
    """Scheduler is a TaskiqScheduler wired to the module-level broker."""
    assert isinstance(scheduler, TaskiqScheduler)
