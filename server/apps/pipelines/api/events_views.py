"""DMR SSE controller for pipeline run events."""

from collections.abc import AsyncIterator
from http import HTTPStatus
from typing import final

import msgspec
from dmr import Controller, validate
from dmr.components import Query
from dmr.exceptions import NotAuthenticatedError
from dmr.metadata import ResponseSpec
from dmr.negotiation import ContentType
from dmr.plugins.msgspec import MsgspecSerializer
from dmr.streaming import StreamingResponse, streaming_response_spec
from dmr.streaming.sse import SSEController, SSEvent

from server.apps.pipelines.logic.sse_events import (
    PipelineRunEvent,
    RunEventsQuery,
)
from server.apps.pipelines.services.pipeline_run import PipelineRunService
from server.common.redis_client import get_redis


async def produce_pipeline_events(
    run_id: str,
) -> AsyncIterator[SSEvent[PipelineRunEvent]]:
    """Yield typed SSE events from the pipeline Redis pub/sub channel."""
    client = get_redis()
    pubsub = client.pubsub()
    channel = f'pipeline:{run_id}'
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message['type'] != 'message':
                continue
            raw = message['data']
            if isinstance(raw, bytes):
                payload = raw.decode('utf-8')
            else:
                payload = str(raw)
            event = msgspec.json.decode(payload, type=PipelineRunEvent)
            yield SSEvent(event)
    finally:
        await pubsub.unsubscribe(channel)
        await client.aclose()


@final
class RunEventsController(SSEController[MsgspecSerializer]):
    """Stream server-sent events for a pipeline run."""

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
