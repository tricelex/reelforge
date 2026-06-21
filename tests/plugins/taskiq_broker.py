"""Taskiq test fixtures — swap real broker for an in-process no-op broker."""

from collections.abc import AsyncGenerator, Generator
from typing import Any, override
from unittest.mock import patch

import pytest
from taskiq import AsyncBroker, BrokerMessage
from taskiq.decor import AsyncTaskiqDecoratedTask


class _NoOpBroker(AsyncBroker):
    """Broker that accepts task kicks without executing them.

    This prevents background tasks from running against the test DB
    while still allowing kiq() calls to succeed.
    """

    @override
    async def kick(self, message: BrokerMessage) -> None:
        """Accept the message and discard it."""

    @override
    def listen(  # pragma: no cover
        self,
    ) -> AsyncGenerator[bytes]:
        """Not used in tests — returns an empty async generator."""
        return _empty_async_gen()


async def _empty_async_gen() -> AsyncGenerator[bytes]:  # pragma: no cover
    """Yield nothing — satisfies the async generator protocol."""
    return
    yield b''  # type: ignore[unreachable]


@pytest.fixture(autouse=True)
def _taskiq_in_memory() -> Generator[None]:
    import server.common.broker as broker_module
    import server.common.taskiq_sender as sender_module
    from server.apps.main import tasks as tasks_module

    no_op = _NoOpBroker()
    original = broker_module.broker
    original_add_broker: AsyncBroker = tasks_module.add.broker
    original_notify_broker: AsyncBroker = (
        tasks_module.notify_blog_post_created.broker
    )
    original_broker_ready = sender_module._broker_ready

    _swap_broker(tasks_module.add, no_op)
    _swap_broker(tasks_module.notify_blog_post_created, no_op)
    broker_module.broker = no_op  # type: ignore[assignment]
    sender_module._broker_ready = False

    with patch.object(sender_module, 'kiq_task'):
        yield

    broker_module.broker = original
    sender_module._broker_ready = original_broker_ready
    _swap_broker(tasks_module.add, original_add_broker)
    _swap_broker(tasks_module.notify_blog_post_created, original_notify_broker)


def _swap_broker(
    task: AsyncTaskiqDecoratedTask[Any, Any],
    broker: AsyncBroker,
) -> None:
    """Register ``task`` with ``broker`` and update the task's broker ref."""
    task.broker = broker
    broker.local_task_registry[task.task_name] = task
