"""Enqueue Taskiq tasks from synchronous Django code.

Do not call ``async_to_sync(task.kiq)(...)`` directly: each invocation may
use a different event loop, which closes the RabbitMQ channel opened by
``broker.startup()``.  Route all sync enqueues through ``kiq_task``.
"""

import asyncio
import threading
from typing import Any

from server.common.broker import broker

_broker_ready = False
_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_lock = threading.Lock()


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
    future.result()


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
    await _ensure_broker_started()
    await task.kiq(*args, **kwargs)


def kiq_task(task: Any, *args: Any, **kwargs: Any) -> None:
    """Enqueue a Taskiq task from synchronous code."""
    _run_async(_enqueue(task, args, kwargs))
