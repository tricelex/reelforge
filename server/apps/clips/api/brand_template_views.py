"""DMR controllers for clip brand templates."""

from http import HTTPStatus
from typing import final, override

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from dmr import Body, Controller, modify
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType
from dmr.metadata import ResponseSpec
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.clips.brand_template_services import ClipBrandTemplateService
from server.apps.clips.logic.value_objects import (
    ClipBrandTemplateCreatePayload,
    ClipBrandTemplateListPayload,
    ClipBrandTemplatePatchPayload,
    ClipBrandTemplatePayload,
)
from server.apps.core.auth import require_operator
from server.common.auth import (
    JWTAuthenticatedMixin,
    get_request_user,
    jwt_sync_auth,
)
from server.common.di import HasContainer


@final
class BrandTemplateCollectionController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List and create clip brand templates."""

    auth = (jwt_sync_auth,)

    def get(self) -> ClipBrandTemplateListPayload:
        """Return brand templates for a channel."""
        channel_id = self.request.GET.get('channel_id')
        include_archived = self.request.GET.get('include_archived') == '1'
        limit_raw = self.request.GET.get('limit', '50')
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 50
        return self.resolve(ClipBrandTemplateService).list_templates(
            channel_id=channel_id,
            include_archived=include_archived,
            limit=limit,
        )

    @modify(status_code=HTTPStatus.CREATED)
    def post(
        self,
        parsed_body: Body[ClipBrandTemplateCreatePayload],
    ) -> ClipBrandTemplatePayload:
        """Create a brand template."""
        require_operator(get_request_user(self.request))
        return self.resolve(ClipBrandTemplateService).create_template(
            parsed_body,
        )


@final
class BrandTemplateDetailController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Read and patch one brand template."""

    auth = (jwt_sync_auth,)

    @modify(
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> ClipBrandTemplatePayload:
        """Return one brand template."""
        return self.resolve(ClipBrandTemplateService).get_template(
            str(self.kwargs['template_id']),
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
        parsed_body: Body[ClipBrandTemplatePatchPayload],
    ) -> ClipBrandTemplatePayload:
        """Update brand template fields."""
        require_operator(get_request_user(self.request))
        return self.resolve(ClipBrandTemplateService).patch_template(
            str(self.kwargs['template_id']),
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
            message = (
                '; '.join(exc.messages) if exc.messages else str(exc)
            )
            not_found = 'not found' in message.lower()
            return self.to_error(
                self.format_error(
                    message,
                    error_type=(
                        ErrorType.not_found
                        if not_found
                        else ErrorType.value_error
                    ),
                ),
                status_code=(
                    HTTPStatus.NOT_FOUND
                    if not_found
                    else HTTPStatus.UNPROCESSABLE_ENTITY
                ),
            )
        return super().handle_error(endpoint, controller, exc)


@final
class BrandTemplateDuplicateController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Duplicate a brand template."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.CREATED)
    def post(self) -> ClipBrandTemplatePayload:
        """Clone a brand template."""
        require_operator(get_request_user(self.request))
        return self.resolve(ClipBrandTemplateService).duplicate_template(
            str(self.kwargs['template_id']),
        )
