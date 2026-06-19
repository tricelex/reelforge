"""DMR controllers for characters and niche config."""

from http import HTTPStatus
from typing import final, override

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from dmr import Body, Controller, modify
from dmr.endpoint import Endpoint
from dmr.errors import ErrorType
from dmr.metadata import ResponseSpec
from dmr.plugins.msgspec import MsgspecSerializer

from server.apps.channels.character_selectors import (
    get_character_detail,
    list_characters,
)
from server.apps.channels.character_studio import CharacterStudioService
from server.apps.channels.logic.value_objects import (
    CharacterApprovePayload,
    CharacterCreatePayload,
    CharacterDetailPayload,
    CharacterListPayload,
    CharacterPatchPayload,
    CharacterRoundCreatePayload,
    CharacterRoundResultPayload,
    CharacterSessionPayload,
    CharacterSheetExpandPayload,
    CharacterSheetExpandResultPayload,
    NicheConfigPatchPayload,
    NicheConfigPayload,
)
from server.apps.channels.models import Character
from server.apps.channels.selectors import get_niche_config
from server.apps.channels.services import ChannelService
from server.apps.core.auth import require_operator
from server.common.auth import (
    JWTAuthenticatedMixin,
    get_request_user,
    jwt_sync_auth,
)
from server.common.di import HasContainer


@final
class NicheConfigController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Get or patch channel niche config."""

    auth = (jwt_sync_auth,)

    def get(self) -> NicheConfigPayload:
        """Return niche config."""
        return get_niche_config(str(self.kwargs['channel_id']))

    @modify(status_code=HTTPStatus.OK)
    def patch(
        self,
        parsed_body: Body[NicheConfigPatchPayload],
    ) -> NicheConfigPayload:
        """Update niche config."""
        require_operator(get_request_user(self.request))
        return self.resolve(ChannelService).patch_niche(
            str(self.kwargs['channel_id']),
            parsed_body,
        )


@final
class CharacterCollectionController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """List and create characters."""

    auth = (jwt_sync_auth,)

    def get(self) -> CharacterListPayload:
        """Return characters."""
        return list_characters(
            channel_id=self.request.GET.get('channel'),
            status=self.request.GET.get('status'),
        )

    @modify(status_code=HTTPStatus.CREATED)
    def post(
        self,
        parsed_body: Body[CharacterCreatePayload],
    ) -> CharacterDetailPayload:
        """Create a character."""
        require_operator(get_request_user(self.request))
        return self.resolve(CharacterStudioService).create(parsed_body)


@final
class CharacterDetailController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Get or patch a character."""

    auth = (jwt_sync_auth,)

    @modify(
        extra_responses=[
            ResponseSpec(
                Controller.error_model,
                status_code=HTTPStatus.NOT_FOUND,
            ),
        ],
    )
    def get(self) -> CharacterDetailPayload:
        """Return character detail."""
        return get_character_detail(str(self.kwargs['character_id']))

    @modify(status_code=HTTPStatus.OK)
    def patch(
        self,
        parsed_body: Body[CharacterPatchPayload],
    ) -> CharacterDetailPayload:
        """Update a character."""
        require_operator(get_request_user(self.request))
        return self.resolve(CharacterStudioService).patch(
            str(self.kwargs['character_id']),
            parsed_body,
        )

    @override
    def handle_error(
        self,
        endpoint: Endpoint,
        controller: Controller[MsgspecSerializer],
        exc: Exception,
    ) -> HttpResponse:
        if isinstance(exc, Character.DoesNotExist):  # pragma: no branch
            return self.to_error(
                self.format_error(
                    'Character not found',
                    error_type=ErrorType.not_found,
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        return super().handle_error(endpoint, controller, exc)


@final
class CharacterSessionCollectionController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Start a character generation session."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.CREATED)
    def post(self) -> CharacterSessionPayload:
        """Create a session."""
        require_operator(get_request_user(self.request))
        return self.resolve(CharacterStudioService).start_session(
            str(self.kwargs['character_id']),
        )


@final
class CharacterRoundController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Generate one Studio round."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(
        self,
        parsed_body: Body[CharacterRoundCreatePayload],
    ) -> CharacterRoundResultPayload:
        """Run image generation."""
        require_operator(get_request_user(self.request))
        return self.resolve(CharacterStudioService).generate_round(
            str(self.kwargs['character_id']),
            str(self.kwargs['session_id']),
            parsed_body,
        )


@final
class CharacterApproveController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Approve a character design."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(
        self,
        parsed_body: Body[CharacterApprovePayload],
    ) -> CharacterDetailPayload:
        """Lock winning asset."""
        require_operator(get_request_user(self.request))
        return self.resolve(CharacterStudioService).approve(
            str(self.kwargs['character_id']),
            parsed_body,
        )


@final
class CharacterPromoteController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Promote run-origin character to library."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(self) -> CharacterDetailPayload:
        """Promote character."""
        require_operator(get_request_user(self.request))
        return self.resolve(CharacterStudioService).promote(
            str(self.kwargs['character_id']),
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
class CharacterSheetExpandController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Expand character sheet with labeled variants."""

    auth = (jwt_sync_auth,)

    @modify(status_code=HTTPStatus.OK)
    def post(
        self,
        parsed_body: Body[CharacterSheetExpandPayload],
    ) -> CharacterSheetExpandResultPayload:
        """Generate sheet items."""
        require_operator(get_request_user(self.request))
        return self.resolve(CharacterStudioService).expand_sheet(
            str(self.kwargs['character_id']),
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
