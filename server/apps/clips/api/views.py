"""DMR controllers for clip candidates and gate approval."""

import asyncio
from http import HTTPStatus
from typing import final, override

import msgspec
from django.http import HttpResponse
from dmr import Body, Controller, modify
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType
from dmr.metadata import ResponseSpec
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.clips.logic.value_objects import (
    ApproveGatePayload,
    ClipCandidatePayload,
)
from server.apps.clips.models import ClipCandidate
from server.apps.clips.services import ClipCandidateService
from server.common.di import HasContainer


class _RejectPayload(msgspec.Struct, frozen=True):
    reason: str = ''


class _GateApprovalResult(msgspec.Struct, frozen=True):
    status: str
    approved_count: int


@final
class ClipCandidateListView(
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List all clip candidates for a pipeline run."""

    def get(self) -> list[ClipCandidatePayload]:
        """Return all candidates for the given run_id."""
        return self.resolve(ClipCandidateService).list_for_run(
            str(self.kwargs['run_id']),
        )


@final
class ClipCandidateDetailView(
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Get a single clip candidate by ID."""

    @modify(
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> ClipCandidatePayload:
        """Return one candidate by candidate_id."""
        return self.resolve(ClipCandidateService).get_by_id(
            str(self.kwargs['candidate_id']),
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        """Return 404 when candidate does not exist."""
        if isinstance(exc, ClipCandidate.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Candidate not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(  # pragma: no cover
            endpoint, controller, exc,
        )


@final
class ClipCandidateApproveView(
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Approve a clip candidate for rendering."""

    @modify(status_code=HTTPStatus.OK)
    def post(self) -> ClipCandidatePayload:
        """Mark the candidate APPROVED."""
        return self.resolve(ClipCandidateService).approve(
            str(self.kwargs['candidate_id']),
        )


@final
class ClipCandidateRejectView(
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Reject a clip candidate with an optional reason."""

    @modify(status_code=HTTPStatus.OK)
    def post(
        self,
        parsed_body: Body[_RejectPayload],
    ) -> ClipCandidatePayload:
        """Mark the candidate REJECTED."""
        return self.resolve(ClipCandidateService).reject(
            str(self.kwargs['candidate_id']),
            reason=parsed_body.reason,
        )


@final
class ClipApproveGateView(
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Approve the clip_approval_gate and resume rendering."""

    @modify(status_code=HTTPStatus.OK)
    def post(
        self,
        parsed_body: Body[ApproveGatePayload],
    ) -> _GateApprovalResult:
        """Record gate output and re-advance the pipeline DAG."""
        from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
            approve_gate_impl,
        )

        run_id = str(self.kwargs['run_id'])
        approved_ids = list(parsed_body.approved_candidate_ids)
        asyncio.run(
            approve_gate_impl(
                run_id,
                'clip_approval_gate',
                {'approved_candidate_ids': approved_ids},
            ),
        )
        return _GateApprovalResult(
            status='approved',
            approved_count=len(approved_ids),
        )
