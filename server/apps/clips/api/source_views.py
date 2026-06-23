"""DMR controllers for clip sources."""

from http import HTTPStatus
from typing import final, override

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from dmr import Body, Controller, modify
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType
from dmr.metadata import ResponseSpec
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.clips.logic.value_objects import (
    ClipSourceCreatePayload,
    ClipSourceListPayload,
    ClipSourcePayload,
)
from server.apps.clips.models import ClipSource
from server.apps.clips.source_services import ClipSourceService
from server.apps.core.auth import require_operator
from server.common.auth import (
    JWTAuthenticatedMixin,
    get_request_user,
    jwt_sync_auth,
)
from server.common.di import HasContainer


@final
class ClipSourceCollectionController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List and register clip sources."""

    auth = (jwt_sync_auth,)

    def get(self) -> ClipSourceListPayload:
        """Return clip sources."""
        channel_id = self.request.GET.get('channel_id')
        status = self.request.GET.get('status')
        cursor = self.request.GET.get('cursor')
        limit_raw = self.request.GET.get('limit', '20')
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 20
        return self.resolve(ClipSourceService).list_sources(
            channel_id=channel_id,
            status=status,
            cursor=cursor,
            limit=limit,
        )

    @modify(status_code=HTTPStatus.CREATED)
    def post(
        self,
        parsed_body: Body[ClipSourceCreatePayload],
    ) -> ClipSourcePayload:
        """Register a clip source."""
        require_operator(get_request_user(self.request))
        return self.resolve(ClipSourceService).create(parsed_body)

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
class ClipSourceDetailController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Read one clip source."""

    auth = (jwt_sync_auth,)

    @modify(
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> ClipSourcePayload:
        """Return one clip source."""
        return self.resolve(ClipSourceService).get_source(
            str(self.kwargs['source_id']),
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
        if isinstance(exc, ClipSource.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Clip source not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(endpoint, controller, exc)
