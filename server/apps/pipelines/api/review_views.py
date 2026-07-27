"""DMR controllers for longform review surfaces."""

from http import HTTPStatus
from typing import Any, final, override

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from dmr import Body, Controller, modify
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType
from dmr.metadata import ResponseSpec
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.core.auth import require_operator
from server.apps.pipelines.footage_selectors import get_run_credits
from server.apps.pipelines.logic.value_objects import (
    PreviewPayload,
    PublishMetadataPatchPayload,
    PublishMetadataPayload,
    PublishPayload,
    PublishResultPayload,
    ResearchFootagePayload,
    RunActionResultPayload,
    RunCreditsPayload,
    SceneBreakdownPayload,
    ScenePatchPayload,
    SelectFootageCandidatePayload,
    StoryboardScenePayload,
)
from server.apps.pipelines.models import PipelineRun
from server.apps.pipelines.services.run_review import RunReviewService
from server.common.auth import (
    JWTAuthenticatedMixin,
    get_request_user,
    jwt_sync_auth,
)
from server.common.di import HasContainer


@final
class RunStoryboardController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return storyboard grid for a run."""

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
    def get(self) -> Any:
        """Return storyboard payload, dispatched by blueprint profile."""
        return self.resolve(RunReviewService).get_storyboard(
            str(self.kwargs['run_id']),
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, PipelineRun.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Run not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(endpoint, controller, exc)


@final
class RunSceneBreakdownController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return scene breakdown rows."""

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
    def get(self) -> SceneBreakdownPayload:
        """Return scenes from breakdown stage."""
        return self.resolve(RunReviewService).get_scene_breakdown(
            str(self.kwargs['run_id']),
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, PipelineRun.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Run not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(endpoint, controller, exc)


@final
class RunSceneDetailController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Patch one scene in the breakdown."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def patch(
        self,
        parsed_body: Body[ScenePatchPayload],
    ) -> StoryboardScenePayload:
        """Update scene fields and stale downstream stages."""
        require_operator(get_request_user(self.request))
        return self.resolve(RunReviewService).patch_scene(
            str(self.kwargs['run_id']),
            int(self.kwargs['scene_idx']),
            parsed_body,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, ValidationError):
            return self.to_error(
                self.format_error(
                    '; '.join(exc.messages),
                    error_type=ErrorType.value_error,
                ),
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        return super().handle_error(endpoint, controller, exc)


@final
class RunSceneSelectCandidateController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Swap a documentary scene's footage to a ranked alternate candidate."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(
        self,
        parsed_body: Body[SelectFootageCandidatePayload],
    ) -> RunActionResultPayload:
        """Validate the candidate and requeue footage_prep for this scene."""
        require_operator(get_request_user(self.request))
        return self.resolve(RunReviewService).select_footage_candidate(
            str(self.kwargs['run_id']),
            int(self.kwargs['scene_idx']),
            parsed_body.external_id,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, ValidationError):
            return self.to_error(
                self.format_error(
                    '; '.join(exc.messages),
                    error_type=ErrorType.value_error,
                ),
                status_code=HTTPStatus.BAD_REQUEST,
            )
        return super().handle_error(endpoint, controller, exc)


@final
class RunSceneResearchFootageController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Re-run footage_search for one scene with an operator query."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(
        self,
        parsed_body: Body[ResearchFootagePayload],
    ) -> RunActionResultPayload:
        """Reject an empty query, else requeue footage_search for the scene."""
        require_operator(get_request_user(self.request))
        return self.resolve(RunReviewService).research_footage(
            str(self.kwargs['run_id']),
            int(self.kwargs['scene_idx']),
            parsed_body.query,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, ValidationError):
            return self.to_error(
                self.format_error(
                    '; '.join(exc.messages),
                    error_type=ErrorType.value_error,
                ),
                status_code=HTTPStatus.BAD_REQUEST,
            )
        return super().handle_error(endpoint, controller, exc)


@final
class RunCreditsController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return the attribution block preview for a run."""

    auth = (jwt_sync_auth,)

    def get(self) -> RunCreditsPayload:
        """Return required-first footage credits for this run."""
        return get_run_credits(str(self.kwargs['run_id']))


@final
class RunPreviewController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return presigned preview URL for latest assembly."""

    auth = (jwt_sync_auth,)

    def get(self) -> PreviewPayload:
        """Return preview URL."""
        return self.resolve(RunReviewService).get_preview(
            str(self.kwargs['run_id']),
        )


@final
class RunPublishMetadataController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Read and patch publish metadata for final review."""

    auth = (jwt_sync_auth,)

    def get(self) -> PublishMetadataPayload:
        """Return publish metadata."""
        return self.resolve(RunReviewService).get_publish_metadata(
            str(self.kwargs['run_id']),
        )

    @modify(status_code=HTTPStatus.OK)
    def patch(
        self,
        parsed_body: Body[PublishMetadataPatchPayload],
    ) -> PublishMetadataPayload:
        """Update publish metadata."""
        require_operator(get_request_user(self.request))
        return self.resolve(RunReviewService).patch_publish_metadata(
            str(self.kwargs['run_id']),
            parsed_body,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, ValidationError):
            return self.to_error(
                self.format_error(
                    '; '.join(exc.messages),
                    error_type=ErrorType.value_error,
                ),
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        if isinstance(exc, PipelineRun.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Run not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(endpoint, controller, exc)


@final
class RunPublishController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Approve final gate and resume toward YouTube publish."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(
        self,
        parsed_body: Body[PublishPayload],
    ) -> PublishResultPayload:
        """Trigger publish flow."""
        require_operator(get_request_user(self.request))
        return self.resolve(RunReviewService).publish(
            str(self.kwargs['run_id']),
            parsed_body,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, ValidationError):
            return self.to_error(
                self.format_error(
                    '; '.join(exc.messages),
                    error_type=ErrorType.value_error,
                ),
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        if isinstance(exc, PipelineRun.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Run not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(endpoint, controller, exc)
