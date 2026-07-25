"""DMR controllers for pipeline run operations."""

from http import HTTPStatus
from typing import final, override

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from dmr import Body, Controller, modify
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType
from dmr.metadata import ResponseSpec
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.clips.services import ClipsService
from server.apps.core.auth import require_operator
from server.apps.pipelines.clip_selectors import get_run_transcript
from server.apps.pipelines.gate_selectors import (
    list_gate_catalog,
    list_gates_waiting,
)
from server.apps.pipelines.logic.value_objects import (
    BlueprintListPayload,
    GateApprovePayload,
    GateApproveResultPayload,
    GateCatalogPayload,
    GateWaitingListPayload,
    GateWaitingPayload,
    RerunStagePayload,
    RunActionResultPayload,
    RunAssetListPayload,
    RunCreatePayload,
    RunDetailPayload,
    RunListPayload,
    SseTokenPayload,
    StageOutputPayload,
    TranscriptPayload,
)
from server.apps.pipelines.models import PipelineRun
from server.apps.pipelines.run_asset_selectors import (
    list_blueprints,
    list_run_assets,
)
from server.apps.pipelines.selectors import get_run_detail, list_runs
from server.apps.pipelines.services import PipelineRunService
from server.apps.pipelines.stage_output_selectors import (
    StageNotFound,
    get_stage_output,
)
from server.common.auth import (
    JWTAuthenticatedMixin,
    get_request_user,
    jwt_sync_auth,
)
from server.common.di import HasContainer
from server.common.exceptions import ConflictError
from server.common.storage import PresignUrlHelper


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
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.CONFLICT,
            ),
        ],
    )
    def post(self, parsed_body: Body[RunCreatePayload]) -> RunDetailPayload:
        """Create run and kick orchestrator."""
        require_operator(get_request_user(self.request))
        idempotency_key = self.request.headers.get(
            'Idempotency-Key',
        ) or self.request.META.get('HTTP_IDEMPOTENCY_KEY')
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
        if isinstance(exc, ConflictError):
            return self.to_error(
                self.format_error(
                    str(exc),
                    error_type=ErrorType.value_error,
                ),
                status_code=HTTPStatus.CONFLICT,
            )
        if isinstance(exc, ValidationError):
            messages = exc.messages if hasattr(exc, 'messages') else [str(exc)]
            return self.to_error(
                self.format_error(
                    '; '.join(str(m) for m in messages),
                    error_type=ErrorType.value_error,
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

    @modify(
        status_code=HTTPStatus.OK,
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.BAD_REQUEST,
            ),
        ],
    )
    def post(
        self,
        parsed_body: Body[GateApprovePayload],
    ) -> GateApproveResultPayload:
        """Record gate output and re-advance the pipeline."""
        from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
            _approve_gate_sync,
        )
        from server.apps.pipelines.tasks import (  # noqa: PLC0415
            advance_pipeline,
        )
        from server.common.taskiq_sender import kiq_task  # noqa: PLC0415

        run_id = str(self.kwargs['run_id'])
        gate_key = str(self.kwargs['gate_key'])
        output = _payload_to_dict(parsed_body)
        approved_count: int | None = None
        if gate_key == 'clip_approval_gate':
            approved_raw = output.get('approved_candidate_ids', [])
            if isinstance(approved_raw, list):
                approved_ids = [str(value) for value in approved_raw]
                self.resolve(ClipsService).sync_gate_candidates(
                    run_id,
                    approved_ids,
                )
                approved_count = len(approved_ids)
        _approve_gate_sync(run_id, gate_key, output)
        kiq_task(advance_pipeline, run_id)
        return GateApproveResultPayload(
            status='ok',
            approved_count=approved_count,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        """Map missing parked gate to a 400 response."""
        if isinstance(exc, ValidationError):
            messages = exc.messages if hasattr(exc, 'messages') else [str(exc)]
            return self.to_error(
                self.format_error(
                    '; '.join(str(m) for m in messages),
                    error_type=ErrorType.value_error,
                ),
                status_code=HTTPStatus.BAD_REQUEST,
            )
        return super().handle_error(endpoint, controller, exc)


@final
class RunTranscriptController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return clip transcript for a run."""

    auth = (jwt_sync_auth,)

    def get(self) -> TranscriptPayload:
        """Return transcript words and chapters."""
        return get_run_transcript(
            str(self.kwargs['run_id']),
            self.resolve(PresignUrlHelper),
        )


@final
class RunAssetsController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List presigned URLs for run-owned assets."""

    auth = (jwt_sync_auth,)

    def get(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> RunAssetListPayload:
        """Return paginated run assets."""
        return list_run_assets(
            str(self.kwargs['run_id']),
            self.resolve(PresignUrlHelper),
            cursor=cursor,
            limit=limit,
        )


@final
class RunStageOutputController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return the rendered output of a single pipeline stage."""

    auth = (jwt_sync_auth,)

    @modify(
        status_code=HTTPStatus.OK,
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> StageOutputPayload:
        """Return the stage output payload."""
        return get_stage_output(
            str(self.kwargs['run_id']),
            str(self.kwargs['stage_key']),
            self.resolve(PresignUrlHelper),
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        """Map missing run or unknown stage to a 404."""
        if isinstance(exc, (PipelineRun.DoesNotExist, StageNotFound)):
            return self.to_error(
                self.format_error(
                    'Run or stage not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(endpoint, controller, exc)


@final
class GateCatalogController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List known pipeline gate keys."""

    auth = (jwt_sync_auth,)

    def get(self) -> GateCatalogPayload:
        """Return gate catalog for armed-gates UI."""
        return list_gate_catalog()


@final
class GatesWaitingController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List runs waiting at armed review gates."""

    auth = (jwt_sync_auth,)

    def get(self) -> GateWaitingListPayload:
        """Return waiting gate queue."""
        rows = list_gates_waiting()
        return GateWaitingListPayload(
            items=[
                GateWaitingPayload(
                    run_id=str(row['run_id']),
                    gate_key=str(row['gate_key']),
                    channel_name=str(row['channel_name']),
                    topic=str(row['topic']),
                    spent_usd=str(row['spent_usd']),
                )
                for row in rows
            ],
            total=len(rows),
        )


@final
class BlueprintCollectionController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List active pipeline blueprints."""

    auth = (jwt_sync_auth,)

    def get(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> BlueprintListPayload:
        """Return blueprint summaries."""
        return list_blueprints(cursor=cursor, limit=limit)
