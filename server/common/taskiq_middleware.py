"""Taskiq middleware for Sentry and Logfire observability."""

import contextlib
import contextvars
from typing import Any, override

import logfire
import sentry_sdk
from opentelemetry import trace
from opentelemetry.trace import StatusCode
from taskiq import TaskiqMiddleware
from taskiq.message import TaskiqMessage
from taskiq.result import TaskiqResult

_span_stack: contextvars.ContextVar[contextlib.ExitStack | None] = (
    contextvars.ContextVar('_span_stack', default=None)
)


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
