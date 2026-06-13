"""Tests for server/common/taskiq_middleware.py."""

import asyncio
from unittest.mock import MagicMock, patch

from taskiq.message import TaskiqMessage
from taskiq.result import TaskiqResult

from server.common.taskiq_middleware import (
    ObservabilityMiddleware,
    _span_stack,  # noqa: PLC2701
)


def _make_message(
    task_name: str = 'test_task',
    task_id: str = 'abc-123',
) -> TaskiqMessage:
    return TaskiqMessage(
        task_id=task_id,
        task_name=task_name,
        labels={},
        args=[],
        kwargs={},
    )


def _make_result() -> TaskiqResult[None]:
    return TaskiqResult(
        is_err=False,
        log='',
        return_value=None,
        execution_time=0.0,
    )


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def test_pre_execute_returns_message_unchanged() -> None:
    """pre_execute returns the same message object it receives."""
    middleware = ObservabilityMiddleware()
    message = _make_message()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=None)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    with patch('logfire.span', return_value=mock_ctx):
        result = _run(middleware.pre_execute(message))
    assert result is message


def test_pre_execute_opens_logfire_span_with_task_context() -> None:
    """pre_execute calls logfire.span with the task name and ID."""
    middleware = ObservabilityMiddleware()
    message = _make_message(task_name='my_task', task_id='id-1')
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=None)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    with patch('logfire.span', return_value=mock_ctx) as mock_span:
        _run(middleware.pre_execute(message))
    mock_span.assert_called_once_with(
        'task {task_name}',
        task_name='my_task',
        task_id='id-1',
    )


def test_post_execute_closes_span() -> None:
    """post_execute closes the active ExitStack."""
    middleware = ObservabilityMiddleware()
    message = _make_message()
    result = _make_result()
    mock_stack = MagicMock()

    # asyncio.run() runs the coroutine in a copy of the current context, so
    # ContextVar mutations inside the coroutine do not propagate back.  Run
    # the setup and assertion together inside a single async scope so that
    # _span_stack.set() calls share the same context.
    async def _inner() -> None:
        _span_stack.set(mock_stack)
        await middleware.post_execute(message, result)
        mock_stack.close.assert_called_once()
        assert _span_stack.get() is None

    _run(_inner())


def test_post_execute_handles_no_active_span() -> None:
    """post_execute is a no-op when no span was previously opened."""
    middleware = ObservabilityMiddleware()
    message = _make_message()
    result = _make_result()
    _span_stack.set(None)

    # Should complete without error even with no active span.
    _run(middleware.post_execute(message, result))


def test_on_error_captures_exception_to_sentry_with_task_tags() -> None:
    """on_error sends the exception to Sentry tagged with task name and ID."""
    middleware = ObservabilityMiddleware()
    message = _make_message(task_name='failing_task', task_id='id-2')
    result = _make_result()
    error = ValueError('task failed')
    mock_scope = MagicMock()

    with patch('sentry_sdk.new_scope') as mock_new_scope:
        mock_new_scope.return_value.__enter__ = MagicMock(
            return_value=mock_scope,
        )
        mock_new_scope.return_value.__exit__ = MagicMock(return_value=False)
        _run(middleware.on_error(message, result, error))

    mock_scope.set_tag.assert_any_call('task_name', 'failing_task')
    mock_scope.set_tag.assert_any_call('task_id', 'id-2')
    mock_scope.capture_exception.assert_called_once_with(error)
