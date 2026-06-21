"""Tests for server/common/taskiq_sender.py."""

from unittest.mock import AsyncMock, patch

from server.common import taskiq_sender


def test_enqueue_starts_broker_once() -> None:
    task = AsyncMock()
    task.kiq = AsyncMock(return_value=None)
    with (
        patch.object(taskiq_sender.broker, 'is_worker_process', False),
        patch.object(taskiq_sender.broker, 'startup', AsyncMock()) as startup,
    ):
        taskiq_sender._broker_ready = False
        taskiq_sender._run_async(taskiq_sender._enqueue(task, ('a',), {}))
        taskiq_sender._run_async(taskiq_sender._enqueue(task, ('b',), {}))
    startup.assert_awaited_once()
    assert task.kiq.await_count == 2


def test_ensure_loop_reuses_background_thread() -> None:
    taskiq_sender._loop = None
    taskiq_sender._loop_thread = None
    first = taskiq_sender._ensure_loop()
    second = taskiq_sender._ensure_loop()
    assert first is second
    assert taskiq_sender._loop_thread is not None
    assert taskiq_sender._loop_thread.is_alive()
