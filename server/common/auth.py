"""JWT authentication helpers shared across all apps."""

import datetime as dt
from collections.abc import Sequence
from typing import ClassVar

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from dmr.security import SyncAuth
from dmr.security.jwt.auth import JWTSyncAuth

JWT_ACCESS_LIFETIME = dt.timedelta(hours=3)
JWT_REFRESH_LIFETIME = dt.timedelta(days=7)

jwt_sync_auth = JWTSyncAuth(
    algorithm='HS256',
    verify_expiry=True,
)


class JWTAuthenticatedMixin:
    """Mixin requiring a valid Bearer JWT on all controller methods."""

    auth: ClassVar[Sequence[SyncAuth]] = (jwt_sync_auth,)


def get_request_user(request: object) -> User:
    """Return the authenticated Django user from a DMR request."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        msg = 'Authentication required'
        raise PermissionDenied(msg)
    return user  # type: ignore[no-any-return]
