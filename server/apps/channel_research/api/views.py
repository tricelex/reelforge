"""DMR controllers for channel research APIs."""

from http import HTTPStatus
from typing import final, override

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from dmr import Body, Controller, modify
from dmr.components import Query
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType
from dmr.metadata import ResponseSpec
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.channel_research.logic.value_objects import (
    ChannelResearchCreatePayload,
    ChannelResearchJobPayload,
    ChannelResearchListPayload,
    ChannelResearchListQuery,
    ChannelResearchSpecPatchPayload,
    ChannelSpecImportResultPayload,
    ChannelSpecPayload,
    ChannelSpecValidateResultPayload,
)
from server.apps.channel_research.models import ChannelResearchJob
from server.apps.channel_research.services import ChannelResearchService
from server.apps.core.auth import require_operator
from server.common.auth import (
    JWTAuthenticatedMixin,
    get_request_user,
    jwt_sync_auth,
)
from server.common.di import HasContainer
from server.services.channel_spec_importer import import_channel_spec


def _validation_or_not_found(
    controller: Controller[MsgspecSerializer],
    _endpoint: Endpoint,
    exc: Exception,
) -> HttpResponse | None:
    if isinstance(exc, ValidationError):
        return controller.to_error(
            controller.format_error(
                '; '.join(exc.messages),
                error_type=ErrorType.value_error,
            ),
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    if isinstance(exc, ChannelResearchJob.DoesNotExist):
        return controller.to_error(
            controller.format_error(
                'Job not found',
                error_type=ErrorType.not_found,
            ),
            status_code=HTTPStatus.NOT_FOUND,
        )
    return None


@final
class ChannelResearchCollectionController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List and create channel research jobs."""

    auth = (jwt_sync_auth,)

    def get(
        self,
        *,
        parsed_query: Query[ChannelResearchListQuery],
    ) -> ChannelResearchListPayload:
        """Return cursor-paginated jobs."""
        return self.resolve(ChannelResearchService).list_jobs(
            status=parsed_query.status,
            cursor=parsed_query.cursor,
            limit=parsed_query.limit,
        )

    @modify(status_code=HTTPStatus.CREATED)
    def post(
        self,
        parsed_body: Body[ChannelResearchCreatePayload],
    ) -> ChannelResearchJobPayload:
        """Create a job and enqueue research."""
        user = get_request_user(self.request)
        require_operator(user)
        return self.resolve(ChannelResearchService).create(
            parsed_body,
            created_by_id=user.pk,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        mapped = _validation_or_not_found(self, endpoint, exc)
        if mapped is not None:
            return mapped
        return super().handle_error(endpoint, controller, exc)


@final
class ChannelResearchDetailController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Fetch or patch one research job."""

    auth = (jwt_sync_auth,)

    @modify(
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> ChannelResearchJobPayload:
        """Return one job (poll this while running)."""
        return self.resolve(ChannelResearchService).get(
            str(self.kwargs['job_id']),
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
        parsed_body: Body[ChannelResearchSpecPatchPayload],
    ) -> ChannelResearchJobPayload:
        """Edit channel_spec when the job succeeded."""
        require_operator(get_request_user(self.request))
        return self.resolve(ChannelResearchService).patch_spec(
            str(self.kwargs['job_id']),
            parsed_body,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        mapped = _validation_or_not_found(self, endpoint, exc)
        if mapped is not None:
            return mapped
        return super().handle_error(endpoint, controller, exc)


@final
class ChannelResearchRetryController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Re-enqueue a failed or succeeded research job."""

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
    def post(self) -> ChannelResearchJobPayload:
        """Reset outputs and run research again."""
        require_operator(get_request_user(self.request))
        return self.resolve(ChannelResearchService).retry(
            str(self.kwargs['job_id']),
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        mapped = _validation_or_not_found(self, endpoint, exc)
        if mapped is not None:
            return mapped
        return super().handle_error(endpoint, controller, exc)


@final
class ChannelResearchValidateSpecController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Validate a ChannelSpec JSON document."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(
        self,
        parsed_body: Body[ChannelSpecPayload],
    ) -> ChannelSpecValidateResultPayload:
        """Return ok/errors for the import editor."""
        require_operator(get_request_user(self.request))
        return self.resolve(ChannelResearchService).validate_spec(
            parsed_body,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        mapped = _validation_or_not_found(self, endpoint, exc)
        if mapped is not None:
            return mapped
        return super().handle_error(endpoint, controller, exc)


@final
class ChannelResearchImportController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Atomically import a ChannelSpec into a live channel."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.CREATED)
    def post(
        self,
        parsed_body: Body[ChannelSpecPayload],
    ) -> ChannelSpecImportResultPayload:
        """Create channel, format, templates, character, and seeds."""
        require_operator(get_request_user(self.request))
        return import_channel_spec(parsed_body)

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        mapped = _validation_or_not_found(self, endpoint, exc)
        if mapped is not None:
            return mapped
        return super().handle_error(endpoint, controller, exc)
