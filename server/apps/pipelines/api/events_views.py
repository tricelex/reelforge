"""DMR SSE controller for pipeline run events."""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterable
from http import HTTPStatus
from typing import Any, ClassVar, cast, final, override

import msgspec
from dmr import Controller, validate
from dmr.components import Query
from dmr.exceptions import NotAuthenticatedError
from dmr.metadata import ResponseSpec
from dmr.negotiation import ContentType
from dmr.plugins.msgspec import MsgspecSerializer
from dmr.serializer import BaseSerializer
from dmr.streaming import StreamingResponse, streaming_response_spec
from dmr.streaming.sse import SSEController, SSEvent
from dmr.streaming.sse.validation import (
    SSEPipeline,
    SSEStreamingValidator,
    validate_event_data,
)
from dmr.streaming.validation import validate_event_type

from server.apps.pipelines.logic.sse_events import (
    PipelineRunEvent,
    RunEventsQuery,
)
from server.apps.pipelines.services.pipeline_run import PipelineRunService
from server.common.redis_client import get_redis

# App-owned keepalives (DMR's ping race leaves orphaned _next_event tasks
# on disconnect). Must stay in sync with former SSEController default.
_SSE_PING_SECONDS = 15.0


def _is_comment_ping(event: Any) -> bool:
    return (
        isinstance(event, SSEvent)
        and event.data is None
        and event.comment is not None
    )


def _validate_event_type_allow_ping(
    event: Any,
    model: Any,
    serializer: type[BaseSerializer],
) -> Any:
    if _is_comment_ping(event):
        return event
    return validate_event_type(event, model, serializer)


def _validate_event_data_allow_ping(
    event: Any,
    model: Any,
    serializer: type[BaseSerializer],
) -> Any:
    if _is_comment_ping(event):
        return event
    return validate_event_data(event, model, serializer)


@final
class PipelineSSEValidator(SSEStreamingValidator):
    """Allow comment-only keepalives alongside typed pipeline events."""

    @override
    def validation_pipeline(self) -> Iterable[SSEPipeline]:
        """Skip typed validation for comment-only ping events."""
        return (
            _validate_event_type_allow_ping,
            _validate_event_data_allow_ping,
        )


def _decode_pubsub_event(message: dict[str, Any]) -> PipelineRunEvent | None:
    """Parse a Redis pub/sub message into a typed pipeline event."""
    if message['type'] != 'message':
        return None
    raw = message['data']
    payload = raw.decode('utf-8') if isinstance(raw, bytes) else str(raw)
    return cast(
        PipelineRunEvent,
        msgspec.json.decode(payload, type=PipelineRunEvent),
    )


async def _cancel_task(task: asyncio.Task[Any] | None) -> None:
    """Cancel a task and wait for it to finish cancelling."""
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def produce_pipeline_events(
    run_id: str,
) -> AsyncIterator[SSEvent[PipelineRunEvent | None]]:
    """Yield typed SSE events from the pipeline Redis pub/sub channel.

    Emits comment-only ping events when idle so proxies keep the connection
    open, and cancels outstanding listen tasks on disconnect.
    """
    client = get_redis()
    pubsub = client.pubsub()
    channel = f'pipeline:{run_id}'
    await pubsub.subscribe(channel)
    listen_iter = aiter(pubsub.listen())
    next_msg_task: asyncio.Task[Any] | None = None
    try:
        while True:
            if next_msg_task is None:
                next_msg_task = asyncio.ensure_future(anext(listen_iter))
            ping_task = asyncio.ensure_future(asyncio.sleep(_SSE_PING_SECONDS))
            done, _pending = await asyncio.wait(
                {next_msg_task, ping_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if ping_task in done and next_msg_task not in done:
                yield SSEvent(comment='ping')
                continue
            await _cancel_task(ping_task)
            try:
                message = next_msg_task.result()
            except StopAsyncIteration:
                break
            finally:
                next_msg_task = None
            event = _decode_pubsub_event(message)
            if event is not None:
                yield SSEvent(event)
    finally:
        await _cancel_task(next_msg_task)
        await pubsub.unsubscribe(channel)
        await client.aclose()


@final
class RunEventsController(SSEController[MsgspecSerializer]):
    """Stream server-sent events for a pipeline run."""

    # Disable DMR's built-in ping race; keepalives live in the producer.
    # SSEController narrows this ClassVar to float via its 15.0 default.
    streaming_ping_seconds = None  # type: ignore[assignment]
    streaming_validator_cls: ClassVar[type[SSEStreamingValidator]] = (
        PipelineSSEValidator
    )

    @validate(
        streaming_response_spec(
            SSEvent[PipelineRunEvent],
            content_type=ContentType.event_stream,
        ),
        ResponseSpec(
            Controller.error_model,
            status_code=HTTPStatus.UNAUTHORIZED,
        ),
        ResponseSpec(
            Controller.error_model,
            status_code=HTTPStatus.BAD_REQUEST,
        ),
    )
    async def get(
        self,
        *,
        parsed_query: Query[RunEventsQuery],
    ) -> StreamingResponse:
        """Subscribe to live pipeline events using a short-lived token."""
        run_id = str(self.kwargs['run_id'])
        if not PipelineRunService.validate_sse_token(
            parsed_query.token,
            run_id,
        ):
            raise NotAuthenticatedError
        return self.to_stream(produce_pipeline_events(run_id))
