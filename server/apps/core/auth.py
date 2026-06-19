"""JWT authentication helpers for DMR controllers."""

import datetime as dt
from typing import final

from django.contrib.auth.models import AbstractBaseUser, User
from django.core.exceptions import PermissionDenied
from dmr.security.jwt.auth import JWTSyncAuth

from server.apps.core.logic.constants import UserRole
from server.apps.core.models import UserProfile

jwt_sync_auth = JWTSyncAuth(
    algorithm='HS256',
    verify_expiry=True,
)

JWT_ACCESS_LIFETIME = dt.timedelta(minutes=15)
JWT_REFRESH_LIFETIME = dt.timedelta(days=7)


@final
class JWTAuthenticatedMixin:
    """Mixin requiring a valid Bearer JWT on all controller methods."""

    auth = (jwt_sync_auth,)


def get_user_role(user: AbstractBaseUser) -> str:
    """Return the user's role, creating a default profile if missing."""
    profile, _ = UserProfile.objects.get_or_create(
        user_id=user.pk,
        defaults={'role': UserRole.OPERATOR},
    )
    return str(profile.role)


def require_operator(user: AbstractBaseUser) -> None:
    """Raise PermissionDenied unless the user is an operator."""
    if get_user_role(user) != UserRole.OPERATOR:
        raise PermissionDenied('Operator role required')


def get_request_user(request: object) -> User:
    """Return the authenticated Django user from a DMR request."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        msg = 'Authentication required'
        raise PermissionDenied(msg)
    return user  # type: ignore[no-any-return]
