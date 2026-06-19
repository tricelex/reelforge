"""DMR controllers for pipeline run operations."""

import asyncio
from http import HTTPStatus
from typing import final, override

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from dmr import Body, Controller, modify
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType
from dmr.metadata import ResponseSpec
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.core.auth import (
    JWTAuthenticatedMixin,
    get_request_user,
    jwt_sync_auth,
    require_operator,
)
from server.apps.pipelines.logic.value_objects import (
    GateApprovePayload,
    GateApproveResultPayload,
    RerunStagePayload,
    RunActionResultPayload,
    RunCreatePayload,
    RunDetailPayload,
    RunListPayload,
    SseTokenPayload,
)
from server.apps.pipelines.selectors import get_run_detail, list_runs
from server.apps.pipelines.services import PipelineRunService
from server.apps.pipelines.services.orchestrator import approve_gate_impl
from server.common.di import HasContainer


def _payload_to_dict(payload: GateApprovePayload) -> dict[str, object]:
    """Convert gate payload to orchestrator output dict."""
    result: dict[str, object] = {}
    if payload.approved_candidate_ids is not None:
        result['approved_candidate_ids'] = payload.approved_candidate_ids
    if payload.thumbnail_asset_id is not None:
        result['thumbnail_asset_id'] = payload.thumbnail_asset_id
    if payload.schedule_at is not None:
        result['schedule_at'] = payload.schedule_at
    return result


@final
class RunCollectionController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List and create pipeline runs."""

    auth = (jwt_sync_auth,)

    def get(self) -> RunListPayload:
        """Return cursor-paginated runs."""
        status = self.request.GET.get('status')
        channel_id = self.request.GET.get('channel')
        cursor = self.request.GET.get('cursor')
        limit_raw = self.request.GET.get('limit', '20')
        return list_runs(
            status=status,
            channel_id=channel_id,
            cursor=cursor,
            limit=int(limit_raw),
        )

    @modify(
        status_code=HTTPStatus.CREATED,
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.BAD_REQUEST,
            ),
        ],
    )
    def post(self, parsed_body: Body[RunCreatePayload]) -> RunDetailPayload:
        """Create run and kick orchestrator."""
        require_operator(get_request_user(self.request))
        idempotency_key = self.request.META.get('HTTP_IDEMPOTENCY_KEY')
        return self.resolve(PipelineRunService).create(
            parsed_body,
            idempotency_key=idempotency_key,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        """Map validation failures to 400 responses."""
        if isinstance(exc, ValidationError):
            messages = exc.messages if hasattr(exc, 'messages') else [str(exc)]
            return self.to_error(
                self.format_error(
                    '; '.join(str(m) for m in messages),
                    error_type=ErrorType.bad_request,
                ),
                status_code=HTTPStatus.BAD_REQUEST,
            )
        return super().handle_error(endpoint, controller, exc)


@final
class RunListController(RunCollectionController):
    """Alias kept for backwards-compatible imports in tests."""


@final
class RunCreateController(RunCollectionController):
    """Alias kept for backwards-compatible imports in tests."""


@final
class RunDetailController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return full run detail."""

    auth = (jwt_sync_auth,)

    def get(self) -> RunDetailPayload:
        """Return run detail with stage summaries."""
        return get_run_detail(str(self.kwargs['run_id']))


@final
class RunCancelController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Cancel an in-flight pipeline run."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(self) -> RunActionResultPayload:
        """Cancel the run."""
        require_operator(get_request_user(self.request))
        self.resolve(PipelineRunService).cancel(str(self.kwargs['run_id']))
        return RunActionResultPayload(status='cancelled')


@final
class RunPauseController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Pause a pipeline run."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(self) -> RunActionResultPayload:
        """Pause the run."""
        require_operator(get_request_user(self.request))
        self.resolve(PipelineRunService).pause(str(self.kwargs['run_id']))
        return RunActionResultPayload(status='paused')


@final
class RunResumeController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Resume a paused pipeline run."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(self) -> RunActionResultPayload:
        """Resume the run."""
        require_operator(get_request_user(self.request))
        self.resolve(PipelineRunService).resume(str(self.kwargs['run_id']))
        return RunActionResultPayload(status='resumed')


@final
class RunStageRerunController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Rerun a single pipeline stage."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(
        self,
        parsed_body: Body[RerunStagePayload],
    ) -> RunDetailPayload:
        """Stale downstream and enqueue a fresh stage attempt."""
        require_operator(get_request_user(self.request))
        return self.resolve(PipelineRunService).rerun_stage(
            str(self.kwargs['run_id']),
            str(self.kwargs['stage_key']),
            shard_indices=parsed_body.shard_indices,
        )


@final
class RunEventsTokenController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Issue a short-lived SSE subscription token."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(self) -> SseTokenPayload:
        """Return signed token for SSE stream."""
        return self.resolve(PipelineRunService).issue_sse_token(
            str(self.kwargs['run_id']),
        )


@final
class RunGateApproveController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Approve a parked pipeline gate and resume the DAG."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(
        self,
        parsed_body: Body[GateApprovePayload],
    ) -> GateApproveResultPayload:
        """Record gate output and re-advance the pipeline."""
        run_id = str(self.kwargs['run_id'])
        gate_key = str(self.kwargs['gate_key'])
        asyncio.run(
            approve_gate_impl(
                run_id,
                gate_key,
                _payload_to_dict(parsed_body),
            ),
        )
        return GateApproveResultPayload(status='ok')
