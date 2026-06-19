"""Direct tests for core auth helpers."""

import pytest
from django.contrib.auth.models import AnonymousUser, User
from django.core.exceptions import PermissionDenied

from server.apps.core.auth import get_request_user, require_operator
from server.apps.core.logic.constants import UserRole
from server.apps.core.models import UserProfile


class _FakeRequest:
    """Minimal request stub for auth helper tests."""

    def __init__(self, user: object) -> None:
        self.user = user


@pytest.mark.django_db
def test_require_operator_raises_for_reviewer(reviewer_user: User) -> None:
    """Reviewers are denied operator-only actions."""
    with pytest.raises(PermissionDenied, match='Operator role required'):
        require_operator(reviewer_user)


@pytest.mark.django_db
def test_require_operator_allows_operator(api_user: User) -> None:
    """Operators pass the role check."""
    require_operator(api_user)


@pytest.mark.django_db
def test_get_request_user_raises_when_unauthenticated() -> None:
    """Unauthenticated requests raise PermissionDenied."""
    request = _FakeRequest(AnonymousUser())

    with pytest.raises(PermissionDenied, match='Authentication required'):
        get_request_user(request)


@pytest.mark.django_db
def test_get_request_user_returns_authenticated_user(api_user: User) -> None:
    """Authenticated users are returned from the request."""
    request = _FakeRequest(api_user)

    assert get_request_user(request) is api_user


@pytest.mark.django_db
def test_get_user_role_creates_default_profile(db: None) -> None:
    """Users without profiles default to operator role."""
    from server.apps.core.auth import get_user_role

    user = User.objects.create_user(username='no-profile', password='x')
    assert get_user_role(user) == UserRole.OPERATOR
    assert UserProfile.objects.filter(user=user).exists()
