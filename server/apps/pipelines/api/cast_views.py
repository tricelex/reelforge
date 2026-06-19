"""DMR controllers for run cast operations."""

from http import HTTPStatus
from typing import final, override

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from dmr import Body, Controller, modify
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType
from dmr.metadata import ResponseSpec
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.channels.logic.value_objects import (
    CharacterRoundCreatePayload,
    CharacterRoundResultPayload,
    CharacterSessionPayload,
)
from server.apps.core.auth import require_operator
from server.apps.pipelines.logic.value_objects import (
    RunCastApprovePayload,
    RunCastListPayload,
    RunCastPatchPayload,
    RunCastPayload,
)
from server.apps.pipelines.models import RunCast
from server.apps.pipelines.run_cast_selectors import list_run_cast
from server.apps.pipelines.services.run_cast import RunCastService
from server.common.auth import (
    JWTAuthenticatedMixin,
    get_request_user,
    jwt_sync_auth,
)
from server.common.di import HasContainer


@final
class RunCastCollectionController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List cast for a run."""

    auth = (jwt_sync_auth,)

    def get(self) -> RunCastListPayload:
        """Return run cast."""
        return list_run_cast(str(self.kwargs['run_id']))


@final
class RunCastDetailController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Patch a cast member."""

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
    def patch(
        self,
        parsed_body: Body[RunCastPatchPayload],
    ) -> RunCastPayload:
        """Update cast assignment."""
        require_operator(get_request_user(self.request))
        return self.resolve(RunCastService).patch(
            str(self.kwargs['run_id']),
            str(self.kwargs['cast_id']),
            parsed_body,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, RunCast.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Cast member not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(endpoint, controller, exc)


@final
class RunCastSessionController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Start in-run Studio session for a cast member."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.CREATED)
    def post(self) -> CharacterSessionPayload:
        """Create session."""
        require_operator(get_request_user(self.request))
        return self.resolve(RunCastService).start_session(
            str(self.kwargs['run_id']),
            str(self.kwargs['cast_id']),
        )


@final
class RunCastRoundController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Generate round for cast member session."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(
        self,
        parsed_body: Body[CharacterRoundCreatePayload],
    ) -> CharacterRoundResultPayload:
        """Generate candidates."""
        require_operator(get_request_user(self.request))
        return self.resolve(RunCastService).generate_round(
            str(self.kwargs['run_id']),
            str(self.kwargs['cast_id']),
            str(self.kwargs['session_id']),
            parsed_body,
        )


@final
class RunCastApproveController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Approve cast member design."""

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
    def post(
        self,
        parsed_body: Body[RunCastApprovePayload],
    ) -> RunCastPayload:
        """Approve design."""
        require_operator(get_request_user(self.request))
        return self.resolve(RunCastService).approve(
            str(self.kwargs['run_id']),
            str(self.kwargs['cast_id']),
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
        if isinstance(exc, RunCast.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Cast member not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(endpoint, controller, exc)
