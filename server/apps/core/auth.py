"""JWT authentication helpers for the core app (role enforcement)."""

from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import PermissionDenied

from server.apps.core.logic.constants import UserRole
from server.apps.core.models import UserProfile
from server.common.auth import JWT_ACCESS_LIFETIME as JWT_ACCESS_LIFETIME
from server.common.auth import JWT_REFRESH_LIFETIME as JWT_REFRESH_LIFETIME
from server.common.auth import JWTAuthenticatedMixin as JWTAuthenticatedMixin
from server.common.auth import get_request_user as get_request_user
from server.common.auth import jwt_sync_auth as jwt_sync_auth


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
