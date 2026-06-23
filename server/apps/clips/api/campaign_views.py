"""DMR controllers for clip campaigns and earnings."""

from http import HTTPStatus
from typing import final, override

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from dmr import Body, Controller, modify
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType
from dmr.metadata import ResponseSpec
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.clips.campaign_services import ClipCampaignService
from server.apps.clips.logic.value_objects import (
    ClipCampaignCreatePayload,
    ClipCampaignListPayload,
    ClipCampaignPatchPayload,
    ClipCampaignPayload,
    EarningCreatePayload,
    EarningListPayload,
    EarningPayload,
)
from server.apps.clips.models import ClipCampaign, Earning
from server.apps.core.auth import require_operator
from server.common.auth import (
    JWTAuthenticatedMixin,
    get_request_user,
    jwt_sync_auth,
)
from server.common.di import HasContainer


@final
class CampaignCollectionController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List and create clip campaigns."""

    auth = (jwt_sync_auth,)

    def get(self) -> ClipCampaignListPayload:
        """Return campaigns."""
        channel_id = self.request.GET.get('channel_id')
        limit_raw = self.request.GET.get('limit', '20')
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 20
        return self.resolve(ClipCampaignService).list_campaigns(
            channel_id=channel_id,
            limit=limit,
        )

    @modify(status_code=HTTPStatus.CREATED)
    def post(
        self,
        parsed_body: Body[ClipCampaignCreatePayload],
    ) -> ClipCampaignPayload:
        """Create a campaign."""
        require_operator(get_request_user(self.request))
        return self.resolve(ClipCampaignService).create_campaign(parsed_body)


@final
class CampaignDetailController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Read and patch one campaign."""

    auth = (jwt_sync_auth,)

    @modify(
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> ClipCampaignPayload:
        """Return one campaign."""
        return self.resolve(ClipCampaignService).get_campaign(
            str(self.kwargs['campaign_id']),
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
        parsed_body: Body[ClipCampaignPatchPayload],
    ) -> ClipCampaignPayload:
        """Update campaign fields."""
        require_operator(get_request_user(self.request))
        return self.resolve(ClipCampaignService).patch_campaign(
            str(self.kwargs['campaign_id']),
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
        if isinstance(exc, ClipCampaign.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Campaign not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(endpoint, controller, exc)


@final
class EarningCollectionController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List and create earnings."""

    auth = (jwt_sync_auth,)

    def get(self) -> EarningListPayload:
        """Return earning rows."""
        campaign_id = self.request.GET.get('campaign')
        return self.resolve(ClipCampaignService).list_earnings(
            campaign_id=campaign_id,
        )

    @modify(
        status_code=HTTPStatus.CREATED,
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def post(
        self,
        parsed_body: Body[EarningCreatePayload],
    ) -> EarningPayload:
        """Record a manual earning."""
        require_operator(get_request_user(self.request))
        return self.resolve(ClipCampaignService).create_earning(parsed_body)

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
        if isinstance(exc, (ClipCampaign.DoesNotExist, Earning.DoesNotExist)):
            return self.to_error(
                self.format_error(
                    'Resource not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(endpoint, controller, exc)
