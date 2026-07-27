"""Enqueue Taskiq tasks from synchronous Django code.

Do not call ``task.kiq(...)`` or ``async_to_sync(task.kiq)(...)`` directly:
each ad-hoc call may use a different event loop, which closes the RabbitMQ
channel opened by ``broker.startup()``.

Route all enqueues through this module:

- ``kiq_api_task`` / ``kiq_api_task_async`` — api RabbitMQ queue
- ``kiq_render_task`` / ``kiq_render_task_async`` — render RabbitMQ queue
- ``kiq_task`` / ``kiq_task_async`` — aliases for the api queue
"""

import asyncio
import threading
from typing import Any

from taskiq import AsyncBroker

from server.common.broker import api_broker, render_broker

# Backward-compatible alias used by tests and legacy imports.
broker = api_broker

#: Hard ceiling for one enqueue round-trip to RabbitMQ. Without it a wedged
#: broker channel blocks the calling web request forever.
ENQUEUE_TIMEOUT_SEC = 15.0


class TaskEnqueueError(RuntimeError):
    """Raised when a task could not be handed to the broker in time."""


class _BrokerSender:
    """Persistent asyncio loop + broker startup for one RabbitMQ queue."""

    def __init__(self, broker: AsyncBroker, thread_name: str) -> None:
        self._broker = broker
        self._thread_name = thread_name
        self._broker_ready = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None:
                return self._loop
            loop = asyncio.new_event_loop()

            def _run() -> None:
                asyncio.set_event_loop(loop)
                loop.run_forever()

            self._loop_thread = threading.Thread(
                target=_run,
                daemon=True,
                name=self._thread_name,
            )
            self._loop_thread.start()
            self._loop = loop
            return loop

    def _mark_broker_stale(self) -> None:
        self._broker_ready = False

    async def _ensure_broker_started(self) -> None:
        if self._broker.is_worker_process or self._broker_ready:
            return
        await self._broker.startup()
        self._broker_ready = True

    async def _enqueue_inner(
        self,
        task: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        await self._ensure_broker_started()
        await task.kiq(*args, **kwargs)

    async def _enqueue(
        self,
        task: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        await asyncio.wait_for(
            self._enqueue_inner(task, args, kwargs),
            timeout=ENQUEUE_TIMEOUT_SEC,
        )

    async def _enqueue_in_worker(
        self,
        task: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        await task.kiq(*args, **kwargs)

    def _run_async(self, coro: Any) -> None:
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            future.result(timeout=ENQUEUE_TIMEOUT_SEC)
        except TimeoutError as exc:
            future.cancel()
            self._mark_broker_stale()
            raise TaskEnqueueError(
                f'Task enqueue timed out after {ENQUEUE_TIMEOUT_SEC:.0f}s',
            ) from exc
        except Exception:
            self._mark_broker_stale()
            raise

    def kiq_task(self, task: Any, *args: Any, **kwargs: Any) -> None:
        """Enqueue a task on this broker from synchronous code."""
        if self._broker.is_worker_process:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                loop.create_task(  # noqa: RUF006
                    self._enqueue_in_worker(task, args, kwargs),
                )
                return
        self._run_async(self._enqueue(task, args, kwargs))

    async def kiq_task_async(
        self,
        task: Any,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Enqueue a task on this broker from asynchronous code."""
        if self._broker.is_worker_process:
            await self._enqueue_in_worker(task, args, kwargs)
            return
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._enqueue(task, args, kwargs),
            loop,
        )
        try:
            await asyncio.wrap_future(future)
        except Exception:
            self._mark_broker_stale()
            raise


_api_sender = _BrokerSender(api_broker, 'taskiq-sender-api')
_render_sender = _BrokerSender(render_broker, 'taskiq-sender-render')


def kiq_api_task(task: Any, *args: Any, **kwargs: Any) -> None:
    """Enqueue a task on the api RabbitMQ queue from synchronous code."""
    _api_sender.kiq_task(task, *args, **kwargs)


async def kiq_api_task_async(task: Any, *args: Any, **kwargs: Any) -> None:
    """Enqueue a task on the api RabbitMQ queue from asynchronous code."""
    await _api_sender.kiq_task_async(task, *args, **kwargs)


def kiq_render_task(task: Any, *args: Any, **kwargs: Any) -> None:
    """Enqueue a task on the render RabbitMQ queue from synchronous code."""
    _render_sender.kiq_task(task, *args, **kwargs)


async def kiq_render_task_async(task: Any, *args: Any, **kwargs: Any) -> None:
    """Enqueue a task on the render RabbitMQ queue from asynchronous code."""
    await _render_sender.kiq_task_async(task, *args, **kwargs)


def kiq_task(task: Any, *args: Any, **kwargs: Any) -> None:
    """Enqueue a task on the api queue (backward-compatible alias)."""
    kiq_api_task(task, *args, **kwargs)


async def kiq_task_async(task: Any, *args: Any, **kwargs: Any) -> None:
    """Enqueue a task on the api queue (backward-compatible alias)."""
    await kiq_api_task_async(task, *args, **kwargs)


def _mark_broker_stale() -> None:
    """Force broker re-startup on the next enqueue after a failure."""
    _api_sender._mark_broker_stale()  # noqa: SLF001


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """Backward-compatible accessor for tests."""
    return _api_sender._ensure_loop()  # noqa: SLF001


def _run_async(coro: Any) -> None:
    """Backward-compatible runner for tests."""
    _api_sender._run_async(coro)  # noqa: SLF001


async def _enqueue(
    task: Any,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    """Backward-compatible enqueue for tests."""
    await _api_sender._enqueue(task, args, kwargs)  # noqa: SLF001


async def _ensure_broker_started() -> None:
    """Backward-compatible broker startup for tests."""
    await _api_sender._ensure_broker_started()  # noqa: SLF001
