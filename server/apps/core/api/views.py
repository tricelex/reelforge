"""DMR controllers for authentication and platform metadata."""

import datetime as dt
from http import HTTPStatus
from typing import Any, Literal, final, override

from dmr import Body, Controller, modify
from dmr.plugins.msgspec import MsgspecSerializer
from dmr.security.jwt.views import (
    ObtainTokensPayload,
    ObtainTokensSyncController,
    RefreshTokenSyncController,
)

from server.apps.core.auth import get_user_role
from server.apps.core.logic.value_objects import (
    EnumsPayload,
    LoginPayload,
    RefreshTokenPayload,
    TokenPairPayload,
    UserMePayload,
)
from server.apps.core.selectors import collect_enums
from server.common.auth import (
    JWT_ACCESS_LIFETIME,
    JWT_REFRESH_LIFETIME,
    JWTAuthenticatedMixin,
    get_request_user,
    jwt_sync_auth,
)
from server.common.di import HasContainer

_ACCESS_JWT_TYPE: Literal['access'] = 'access'
_REFRESH_JWT_TYPE: Literal['refresh'] = 'refresh'


def _make_token_pair(
    controller: ObtainTokensSyncController[Any, Any, Any],
) -> TokenPairPayload:
    """Create access + refresh JWT pair for the authenticated request user."""
    access = controller.create_jwt_token(
        token_type=_ACCESS_JWT_TYPE,
        expiration=dt.datetime.now(dt.UTC) + JWT_ACCESS_LIFETIME,
    )
    refresh = controller.create_jwt_token(
        token_type=_REFRESH_JWT_TYPE,
        expiration=dt.datetime.now(dt.UTC) + JWT_REFRESH_LIFETIME,
    )
    return TokenPairPayload(access_token=access, refresh_token=refresh)


@final
class LoginController(
    ObtainTokensSyncController[
        MsgspecSerializer,
        LoginPayload,  # type: ignore[type-var]
        TokenPairPayload,
    ],
):
    """Mint JWT access + refresh tokens for valid credentials."""

    jwt_expiration = JWT_ACCESS_LIFETIME
    jwt_refresh_expiration = JWT_REFRESH_LIFETIME

    @override
    @modify(status_code=HTTPStatus.OK)
    def post(self, parsed_body: Body[LoginPayload]) -> TokenPairPayload:
        """Authenticate and return token pair."""
        return self.login(parsed_body)

    @override
    def convert_auth_payload(
        self,
        payload: LoginPayload,
    ) -> ObtainTokensPayload:
        """Map login body to django.contrib.auth.authenticate kwargs."""
        return {
            'username': payload.username,
            'password': payload.password,
        }

    @override
    def make_api_response(self) -> TokenPairPayload:
        """Return freshly minted JWT tokens."""
        return _make_token_pair(self)


@final
class RefreshController(
    RefreshTokenSyncController[
        MsgspecSerializer,
        RefreshTokenPayload,  # type: ignore[type-var]
        TokenPairPayload,
    ],
):
    """Rotate JWT access + refresh tokens."""

    jwt_expiration = JWT_ACCESS_LIFETIME
    jwt_refresh_expiration = JWT_REFRESH_LIFETIME

    @override
    @modify(status_code=HTTPStatus.OK)
    def post(self, parsed_body: Body[RefreshTokenPayload]) -> TokenPairPayload:
        """Validate refresh token and return a new token pair."""
        return self.refresh(parsed_body)

    @override
    def convert_refresh_payload(self, payload: RefreshTokenPayload) -> str:
        """Extract refresh token string from request body."""
        return payload.refresh_token

    @override
    def make_api_response(self) -> TokenPairPayload:
        """Return freshly minted JWT tokens."""
        return _make_token_pair(self)  # type: ignore[arg-type]


@final
class MeController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return the currently authenticated user."""

    auth = (jwt_sync_auth,)

    def get(self) -> UserMePayload:
        """Return user id, username, and role."""
        user = get_request_user(self.request)
        return UserMePayload(
            id=user.pk,
            username=user.username,
            role=get_user_role(user),
        )


@final
class EnumsController(
    JWTAuthenticatedMixin,
    HasContainer,
    Controller[MsgspecSerializer],
):
    """Return all TextChoices enums for frontend form builders."""

    auth = (jwt_sync_auth,)

    def get(self) -> EnumsPayload:
        """Return enum registry."""
        return collect_enums()
