"""Auth fixtures for API tests."""

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.core.logic.constants import UserRole
from server.apps.core.models import UserProfile


@pytest.fixture()
def api_user(db: None) -> User:
    """Create an operator user with profile."""
    user = User.objects.create_user(
        username='operator',
        password='test-pass',
    )
    UserProfile.objects.create(user=user, role=UserRole.OPERATOR)
    return user


@pytest.fixture()
def reviewer_user(db: None) -> User:
    """Create a reviewer user with profile."""
    user = User.objects.create_user(
        username='reviewer',
        password='test-pass',
    )
    UserProfile.objects.create(user=user, role=UserRole.REVIEWER)
    return user


@pytest.fixture()
def auth_headers(dmr_client: DMRClient, api_user: User) -> dict[str, str]:
    """Obtain JWT access token and return Authorization header."""
    response = dmr_client.post(
        reverse('api:core:login'),
        data={'username': 'operator', 'password': 'test-pass'},
    )
    assert response.status_code == 200
    token = response.json()['access_token']
    return {'Authorization': f'Bearer {token}'}
