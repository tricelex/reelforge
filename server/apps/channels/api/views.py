"""DMR controllers for channels and YouTube OAuth."""

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
    ChannelBrandingPatchPayload,
    ChannelBrandingPayload,
    ChannelCreatePayload,
    ChannelDetailPayload,
    ChannelListPayload,
    ChannelPatchPayload,
    YouTubeCallbackPayload,
    YouTubeConnectPayload,
    YouTubeConnectResultPayload,
    YouTubeStatusPayload,
)
from server.apps.channels.models import Channel
from server.apps.channels.selectors import (
    get_channel_branding,
    get_channel_detail,
    list_channels,
)
from server.apps.channels.services import ChannelService
from server.apps.core.auth import require_operator
from server.common.auth import (
    JWTAuthenticatedMixin,
    get_request_user,
    jwt_sync_auth,
)
from server.common.di import HasContainer


@final
class ChannelCollectionController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List and create channels."""

    auth = (jwt_sync_auth,)

    def get(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ChannelListPayload:
        """Return paginated channels."""
        active_only = self.request.GET.get('active') == 'true'
        return list_channels(
            active_only=active_only,
            cursor=cursor,
            limit=limit,
        )

    @modify(status_code=HTTPStatus.CREATED)
    def post(
        self,
        parsed_body: Body[ChannelCreatePayload],
    ) -> ChannelDetailPayload:
        """Create a new channel."""
        require_operator(get_request_user(self.request))
        return self.resolve(ChannelService).create(parsed_body)


@final
class ChannelDetailController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Get or patch a channel."""

    auth = (jwt_sync_auth,)

    @modify(
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> ChannelDetailPayload:
        """Return channel detail."""
        return get_channel_detail(str(self.kwargs['channel_id']))

    @modify(status_code=HTTPStatus.OK)
    def patch(
        self,
        parsed_body: Body[ChannelPatchPayload],
    ) -> ChannelDetailPayload:
        """Update channel fields."""
        require_operator(get_request_user(self.request))
        return self.resolve(ChannelService).patch(
            str(self.kwargs['channel_id']),
            parsed_body,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, Channel.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Channel not found',
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
class ChannelBrandingController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Get or patch channel branding."""

    auth = (jwt_sync_auth,)

    def get(self) -> ChannelBrandingPayload:
        """Return branding config."""
        return get_channel_branding(str(self.kwargs['channel_id']))

    @modify(status_code=HTTPStatus.OK)
    def patch(
        self,
        parsed_body: Body[ChannelBrandingPatchPayload],
    ) -> ChannelBrandingPayload:
        """Update branding."""
        require_operator(get_request_user(self.request))
        return self.resolve(ChannelService).patch_branding(
            str(self.kwargs['channel_id']),
            parsed_body,
        )


@final
class YouTubeConnectController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return YouTube OAuth authorization URL."""

    auth = (jwt_sync_auth,)

    def get(self) -> YouTubeConnectPayload:
        """Build OAuth URL for the channel."""
        require_operator(get_request_user(self.request))
        redirect_uri = self.request.GET.get('redirect_uri', '')
        if not redirect_uri:
            msg = 'redirect_uri query parameter is required'
            raise ValidationError(msg)
        return self.resolve(ChannelService).youtube_connect_url(
            str(self.kwargs['channel_id']),
            redirect_uri,
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
class YouTubeCallbackController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Complete YouTube OAuth with authorization code."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(
        self,
        parsed_body: Body[YouTubeCallbackPayload],
    ) -> YouTubeConnectResultPayload:
        """Exchange code for tokens."""
        require_operator(get_request_user(self.request))
        return self.resolve(ChannelService).youtube_complete_oauth(
            str(self.kwargs['channel_id']),
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
class YouTubeStatusController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return YouTube connection status."""

    auth = (jwt_sync_auth,)

    def get(self) -> YouTubeStatusPayload:
        """Return whether YouTube is connected."""
        return self.resolve(ChannelService).youtube_status(
            str(self.kwargs['channel_id']),
        )
