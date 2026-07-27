"""Taskiq middleware for DB hygiene and observability."""

import contextlib
import contextvars
from typing import Any, override

import logfire
import sentry_sdk
from asgiref.sync import sync_to_async
from django.db import close_old_connections
from opentelemetry import trace
from opentelemetry.trace import StatusCode
from taskiq import TaskiqMiddleware
from taskiq.message import TaskiqMessage
from taskiq.result import TaskiqResult

_span_stack: contextvars.ContextVar[contextlib.ExitStack | None] = (
    contextvars.ContextVar('_span_stack', default=None)
)

# Run on the thread-sensitive executor so the same thread-local connection
# used by sync_to_async ORM work is refreshed.
_close_old_connections = sync_to_async(close_old_connections)


class DjangoDbMiddleware(TaskiqMiddleware):
    """Close stale Django DB connections around each Taskiq task."""

    @override
    async def pre_execute(
        self,
        message: TaskiqMessage,
    ) -> TaskiqMessage:
        """Drop unusable/obsolete connections before the task runs."""
        await _close_old_connections()
        return message

    @override
    async def post_execute(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
    ) -> None:
        """Drop connections that became unusable during the task."""
        await _close_old_connections()

    @override
    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
        exception: BaseException,
    ) -> None:
        """Drop connections after a failed task (may leave errors_occurred)."""
        await _close_old_connections()


class ObservabilityMiddleware(TaskiqMiddleware):
    """Wraps each Taskiq task with a Logfire span and Sentry error capture."""

    @override
    async def pre_execute(
        self,
        message: TaskiqMessage,
    ) -> TaskiqMessage:
        """Open a Logfire span tagged with task name and ID."""
        stack = contextlib.ExitStack()
        stack.enter_context(
            logfire.span(
                'task {task_name}',
                task_name=message.task_name,
                task_id=message.task_id,
                logical_queue=message.labels.get('queue'),
            ),
        )
        _span_stack.set(stack)
        return message

    @override
    async def post_execute(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
    ) -> None:
        """Close the Logfire span on normal task completion."""
        stack = _span_stack.get()
        if stack is not None:
            stack.close()
            _span_stack.set(None)

    @override
    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
        exception: BaseException,
    ) -> None:
        """Capture exception to Sentry and mark the Logfire span as failed."""
        with sentry_sdk.new_scope() as scope:
            scope.set_tag('task_name', message.task_name)
            scope.set_tag('task_id', message.task_id)
            scope.capture_exception(exception)
        span = trace.get_current_span()
        span.record_exception(exception)
        span.set_status(StatusCode.ERROR, str(exception))
