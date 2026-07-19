"""Enqueue Taskiq tasks from synchronous Django code.

Do not call ``task.kiq(...)`` or ``async_to_sync(task.kiq)(...)`` directly:
each ad-hoc call may use a different event loop, which closes the RabbitMQ
channel opened by ``broker.startup()``.

Route all enqueues through this module:

- ``kiq_task`` — from synchronous Django code (views, services, event handlers)
- ``kiq_task_async`` — from ``async def`` code (orchestrator, executor)
"""

import asyncio
import threading
from typing import Any

from server.common.broker import broker

#: Hard ceiling for one enqueue round-trip to RabbitMQ. Without it a wedged
#: broker channel blocks the calling web request forever.
ENQUEUE_TIMEOUT_SEC = 15.0

_broker_ready = False
_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_lock = threading.Lock()


class TaskEnqueueError(RuntimeError):
    """Raised when a task could not be handed to the broker in time."""


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop, _loop_thread
    with _lock:
        if _loop is not None:
            return _loop
        loop = asyncio.new_event_loop()

        def _run() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        _loop_thread = threading.Thread(
            target=_run,
            daemon=True,
            name='taskiq-sender',
        )
        _loop_thread.start()
        _loop = loop
        return loop


def _run_async(coro: Any) -> None:
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        future.result(timeout=ENQUEUE_TIMEOUT_SEC)
    except TimeoutError as exc:
        future.cancel()
        _mark_broker_stale()
        raise TaskEnqueueError(
            f'Task enqueue timed out after {ENQUEUE_TIMEOUT_SEC:.0f}s',
        ) from exc
    except Exception:
        _mark_broker_stale()
        raise


def _mark_broker_stale() -> None:
    """Force broker re-startup on the next enqueue after a failure."""
    global _broker_ready  # noqa: PLW0603
    _broker_ready = False


async def _ensure_broker_started() -> None:
    global _broker_ready
    if broker.is_worker_process or _broker_ready:
        return
    await broker.startup()
    _broker_ready = True


async def _enqueue(
    task: Any,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    await asyncio.wait_for(
        _enqueue_inner(task, args, kwargs),
        timeout=ENQUEUE_TIMEOUT_SEC,
    )


async def _enqueue_inner(
    task: Any,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    await _ensure_broker_started()
    await task.kiq(*args, **kwargs)


async def _enqueue_in_worker(
    task: Any,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    """Enqueue on the worker's running loop (broker already started there)."""
    await task.kiq(*args, **kwargs)


def kiq_task(task: Any, *args: Any, **kwargs: Any) -> None:
    """Enqueue a Taskiq task from synchronous code."""
    if broker.is_worker_process:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            loop.create_task(_enqueue_in_worker(task, args, kwargs))
            return
    _run_async(_enqueue(task, args, kwargs))


async def kiq_task_async(task: Any, *args: Any, **kwargs: Any) -> None:
    """Enqueue a Taskiq task from asynchronous code.

    Uses the same persistent sender loop as ``kiq_task`` so broker startup
    and RabbitMQ channels stay on one event loop.
    """
    if broker.is_worker_process:
        await _enqueue_in_worker(task, args, kwargs)
        return
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(
        _enqueue(task, args, kwargs),
        loop,
    )
    try:
        await asyncio.wrap_future(future)
    except Exception:
        _mark_broker_stale()
        raise
