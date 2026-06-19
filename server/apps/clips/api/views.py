"""DMR controllers for clip candidates and related resources."""

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
    ApproveAllResultPayload,
    ClipCandidateListPayload,
    ClipCandidatePatchPayload,
    ClipCandidatePayload,
    ClipLayoutConfigPatchPayload,
    ClipLayoutConfigPayload,
    ClipOverlayListPayload,
    ClipPostCreatePayload,
    ClipPostListPayload,
    ClipPostPatchPayload,
    ClipPostPayload,
    ClipPreviewStatusPayload,
    ClipRenderPayload,
    ClipStyleConfigPatchPayload,
    ClipStyleConfigPayload,
    ClipTimedOverlayCreatePayload,
    ClipTimedOverlayPatchPayload,
    ClipTimedOverlayPayload,
)
from server.apps.clips.models import (
    ClipCandidate,
    ClipLayoutConfig,
    ClipPost,
    ClipStyleConfig,
    ClipTimedOverlay,
)
from server.apps.clips.services import ClipsService
from server.common.auth import JWTAuthenticatedMixin, jwt_sync_auth
from server.common.di import HasContainer


class _RejectPayload(msgspec.Struct, frozen=True):
    reason: str = ''


@final
class ClipCandidateListView(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List all clip candidates for a pipeline run."""

    auth = (jwt_sync_auth,)

    def get(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ClipCandidateListPayload:
        """Return paginated candidates for the given run_id."""
        return self.resolve(ClipsService).list_for_run(
            str(self.kwargs['run_id']),
            cursor=cursor,
            limit=limit,
        )


@final
class ClipCandidateApproveAllView(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Bulk-approve all proposed candidates on a run."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(self) -> ApproveAllResultPayload:
        """Approve every PROPOSED candidate."""
        return self.resolve(ClipsService).approve_all(
            str(self.kwargs['run_id']),
        )


@final
class ClipCandidateDetailView(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Get or patch a single clip candidate."""

    auth = (jwt_sync_auth,)

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
        return self.resolve(ClipsService).get_by_id(
            str(self.kwargs['candidate_id']),
        )

    @modify(
        status_code=HTTPStatus.OK,
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def patch(
        self,
        parsed_body: Body[ClipCandidatePatchPayload],
    ) -> ClipCandidatePayload:
        """Update editable candidate fields."""
        return self.resolve(ClipsService).patch(
            str(self.kwargs['candidate_id']),
            parsed_body,
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
            endpoint,
            controller,
            exc,
        )


@final
class ClipCandidateApproveView(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Approve a clip candidate for rendering."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(self) -> ClipCandidatePayload:
        """Mark the candidate APPROVED."""
        return self.resolve(ClipsService).approve(
            str(self.kwargs['candidate_id']),
        )


@final
class ClipCandidateRejectView(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Reject a clip candidate with an optional reason."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(
        self,
        parsed_body: Body[_RejectPayload],
    ) -> ClipCandidatePayload:
        """Mark the candidate REJECTED."""
        return self.resolve(ClipsService).reject(
            str(self.kwargs['candidate_id']),
            reason=parsed_body.reason,
        )


@final
class ClipCandidateRenderView(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return presigned URL for a rendered clip."""

    auth = (jwt_sync_auth,)

    def get(self) -> ClipRenderPayload:
        """Return render asset URL."""
        return self.resolve(ClipsService).get_render(
            str(self.kwargs['candidate_id']),
        )


@final
class ClipCandidatePreviewView(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Trigger a lightweight preview render."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.ACCEPTED)
    def post(self) -> ClipPreviewStatusPayload:
        """Queue preview render."""
        return self.resolve(ClipsService).trigger_preview(
            str(self.kwargs['candidate_id']),
        )


@final
class ClipCandidatePreviewStatusView(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Poll preview render status."""

    auth = (jwt_sync_auth,)

    def get(self) -> ClipPreviewStatusPayload:
        """Return preview status."""
        return self.resolve(ClipsService).get_preview_status(
            str(self.kwargs['candidate_id']),
        )


@final
class ClipLayoutConfigView(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Get or patch layout config for a candidate."""

    auth = (jwt_sync_auth,)

    @modify(
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> ClipLayoutConfigPayload:
        """Return layout config."""
        return self.resolve(ClipsService).get_layout(
            str(self.kwargs['candidate_id']),
        )

    @modify(status_code=HTTPStatus.OK)
    def patch(
        self,
        parsed_body: Body[ClipLayoutConfigPatchPayload],
    ) -> ClipLayoutConfigPayload:
        """Update layout config."""
        return self.resolve(ClipsService).patch_layout(
            str(self.kwargs['candidate_id']),
            parsed_body,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, ClipLayoutConfig.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Layout config not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(  # pragma: no cover
            endpoint,
            controller,
            exc,
        )


@final
class ClipStyleConfigView(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Get or patch style config for a candidate."""

    auth = (jwt_sync_auth,)

    @modify(
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> ClipStyleConfigPayload:
        """Return style config."""
        return self.resolve(ClipsService).get_style(
            str(self.kwargs['candidate_id']),
        )

    @modify(status_code=HTTPStatus.OK)
    def patch(
        self,
        parsed_body: Body[ClipStyleConfigPatchPayload],
    ) -> ClipStyleConfigPayload:
        """Update style config."""
        return self.resolve(ClipsService).patch_style(
            str(self.kwargs['candidate_id']),
            parsed_body,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, ClipStyleConfig.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Style config not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(  # pragma: no cover
            endpoint,
            controller,
            exc,
        )


@final
class ClipTimedOverlayCollectionView(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List or create timed overlays."""

    auth = (jwt_sync_auth,)

    def get(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ClipOverlayListPayload:
        """Return paginated overlays for a candidate."""
        return self.resolve(ClipsService).list_overlays(
            str(self.kwargs['candidate_id']),
            cursor=cursor,
            limit=limit,
        )

    @modify(status_code=HTTPStatus.CREATED)
    def post(
        self,
        parsed_body: Body[ClipTimedOverlayCreatePayload],
    ) -> ClipTimedOverlayPayload:
        """Create a timed overlay."""
        return self.resolve(ClipsService).create_overlay(
            str(self.kwargs['candidate_id']),
            parsed_body,
        )


@final
class ClipTimedOverlayDetailView(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Get, patch, or delete one timed overlay."""

    auth = (jwt_sync_auth,)

    @modify(
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> ClipTimedOverlayPayload:
        """Return one overlay."""
        return self.resolve(ClipsService).get_overlay(
            str(self.kwargs['candidate_id']),
            str(self.kwargs['overlay_id']),
        )

    @modify(status_code=HTTPStatus.OK)
    def patch(
        self,
        parsed_body: Body[ClipTimedOverlayPatchPayload],
    ) -> ClipTimedOverlayPayload:
        """Update one overlay."""
        return self.resolve(ClipsService).patch_overlay(
            str(self.kwargs['candidate_id']),
            str(self.kwargs['overlay_id']),
            parsed_body,
        )

    @modify(status_code=HTTPStatus.NO_CONTENT)
    def delete(self) -> None:
        """Delete one overlay."""
        self.resolve(ClipsService).delete_overlay(
            str(self.kwargs['candidate_id']),
            str(self.kwargs['overlay_id']),
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, ClipTimedOverlay.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Overlay not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(  # pragma: no cover
            endpoint,
            controller,
            exc,
        )


@final
class ClipPostCollectionView(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List or create distribution posts."""

    auth = (jwt_sync_auth,)

    def get(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ClipPostListPayload:
        """Return paginated posts for a candidate."""
        return self.resolve(ClipsService).list_posts(
            str(self.kwargs['candidate_id']),
            cursor=cursor,
            limit=limit,
        )

    @modify(status_code=HTTPStatus.CREATED)
    def post(
        self,
        parsed_body: Body[ClipPostCreatePayload],
    ) -> ClipPostPayload:
        """Create a distribution post."""
        return self.resolve(ClipsService).create_post(
            str(self.kwargs['candidate_id']),
            parsed_body,
        )


@final
class ClipPostDetailView(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Get or patch one distribution post."""

    auth = (jwt_sync_auth,)

    @modify(
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> ClipPostPayload:
        """Return one post."""
        return self.resolve(ClipsService).get_post(
            str(self.kwargs['candidate_id']),
            str(self.kwargs['post_id']),
        )

    @modify(status_code=HTTPStatus.OK)
    def patch(
        self,
        parsed_body: Body[ClipPostPatchPayload],
    ) -> ClipPostPayload:
        """Update one post."""
        return self.resolve(ClipsService).patch_post(
            str(self.kwargs['candidate_id']),
            str(self.kwargs['post_id']),
            parsed_body,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, ClipPost.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Post not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(  # pragma: no cover
            endpoint,
            controller,
            exc,
        )
