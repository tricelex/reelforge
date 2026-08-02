"""DMR controllers for editor-handoff package status and rebuild."""

from http import HTTPStatus
from typing import final, override

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from dmr import Controller, modify
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType
from dmr.metadata import ResponseSpec
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.core.auth import require_operator
from server.apps.pipelines.logic.value_objects import (
    PackagePayload,
    RebuildPackageResultPayload,
)
from server.apps.pipelines.models import PipelineRun
from server.apps.pipelines.services.editor_package import (
    EditorPackageService,
)
from server.common.auth import (
    JWTAuthenticatedMixin,
    get_request_user,
    jwt_sync_auth,
)
from server.common.di import HasContainer


@final
class RunPackageController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return editor-handoff package build status for a run."""

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
    def get(self) -> PackagePayload:
        """Return package status/download URL for the run's latest attempt."""
        return self.resolve(EditorPackageService).get_package(
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
        return super().handle_error(  # pragma: no cover
            endpoint,
            controller,
            exc,
        )


@final
class RunRebuildPackageController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Requeue the editor-handoff tail stages to rebuild the package."""

    auth = (jwt_sync_auth,)

    @modify(
        status_code=HTTPStatus.OK,
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.CONFLICT,
            ),
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def post(self) -> RebuildPackageResultPayload:
        """Require operator, then requeue editor_brief onward."""
        require_operator(get_request_user(self.request))
        return self.resolve(EditorPackageService).rebuild_package(
            str(self.kwargs['run_id']),
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, ValidationError):
            messages = exc.messages if hasattr(exc, 'messages') else [str(exc)]
            return self.to_error(
                self.format_error(
                    '; '.join(str(m) for m in messages),
                    error_type=ErrorType.value_error,
                ),
                status_code=HTTPStatus.CONFLICT,
            )
        if isinstance(exc, PipelineRun.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Run not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(  # pragma: no cover
            endpoint,
            controller,
            exc,
        )
