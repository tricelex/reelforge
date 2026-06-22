"""Tests for server/common/taskiq_sender.py."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from server.common import taskiq_sender

_SERVER_ROOT = Path(__file__).resolve().parents[2] / 'server'
_ALLOWED_DIRECT_KIQ_FILES = {Path('server/common/taskiq_sender.py')}


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


def test_kiq_task_async_uses_worker_loop_when_in_worker() -> None:
    task = AsyncMock()
    task.kiq = AsyncMock(return_value=None)

    async def _inner() -> None:
        with patch.object(taskiq_sender.broker, 'is_worker_process', True):
            await taskiq_sender.kiq_task_async(task, 'run-id')

    asyncio.run(_inner())
    task.kiq.assert_awaited_once_with('run-id')


def test_kiq_task_async_starts_broker_once() -> None:
    task = AsyncMock()
    task.kiq = AsyncMock(return_value=None)

    async def _inner() -> None:
        with (
            patch.object(taskiq_sender.broker, 'is_worker_process', False),
            patch.object(taskiq_sender.broker, 'startup', AsyncMock()) as startup,
        ):
            taskiq_sender._broker_ready = False
            await taskiq_sender.kiq_task_async(task, 'a')
            await taskiq_sender.kiq_task_async(task, 'b')
        startup.assert_awaited_once()
        assert task.kiq.await_count == 2

    asyncio.run(_inner())


def test_kiq_task_async_accepts_pipeline_tasks() -> None:
    """Regression: async orchestrator enqueues must not require manual startup."""
    from server.apps.pipelines.tasks import execute_stage

    async def _inner() -> None:
        await taskiq_sender.kiq_task_async(execute_stage, 'exec-id')

    asyncio.run(_inner())


def test_server_code_never_calls_task_kiq_directly() -> None:
    """All TaskIQ enqueues must route through taskiq_sender helpers."""
    offenders: list[str] = []
    for path in _SERVER_ROOT.rglob('*.py'):
        relative = Path('server') / path.relative_to(_SERVER_ROOT)
        if relative in _ALLOWED_DIRECT_KIQ_FILES:
            continue
        if '.kiq(' in path.read_text(encoding='utf-8'):
            offenders.append(str(relative))
    assert offenders == [], (
        'Use kiq_task / kiq_task_async instead of task.kiq(): '
        + ', '.join(offenders)
    )


def test_ensure_loop_reuses_background_thread() -> None:
    taskiq_sender._loop = None
    taskiq_sender._loop_thread = None
    first = taskiq_sender._ensure_loop()
    second = taskiq_sender._ensure_loop()
    assert first is second
    assert taskiq_sender._loop_thread is not None
    assert taskiq_sender._loop_thread.is_alive()
