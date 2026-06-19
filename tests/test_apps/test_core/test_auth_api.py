"""Tests for core auth API controllers."""

from http import HTTPStatus

import msgspec
import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.core.logic.constants import UserRole
from server.apps.core.logic.value_objects import TokenPairPayload, UserMePayload


@pytest.mark.django_db
def test_login_success(dmr_client: DMRClient, api_user: object) -> None:
    """Valid credentials return access and refresh tokens."""
    response = dmr_client.post(
        reverse('api:core:login'),
        data={'username': 'operator', 'password': 'test-pass'},
    )

    assert response.status_code == HTTPStatus.OK
    parsed = msgspec.convert(response.json(), type=TokenPairPayload)
    assert parsed.access_token
    assert parsed.refresh_token


@pytest.mark.django_db
def test_login_invalid_credentials(
    dmr_client: DMRClient,
    api_user: object,
) -> None:
    """Invalid credentials return 401."""
    response = dmr_client.post(
        reverse('api:core:login'),
        data={'username': 'operator', 'password': 'wrong'},
    )

    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
def test_me_requires_auth(dmr_client: DMRClient) -> None:
    """Me endpoint returns 401 without token."""
    response = dmr_client.get(reverse('api:core:me'))
    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
def test_me_returns_user(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """Me endpoint returns authenticated user details."""
    response = dmr_client.get(
        reverse('api:core:me'),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    parsed = msgspec.convert(response.json(), type=UserMePayload)
    assert parsed.username == 'operator'
    assert parsed.role == UserRole.OPERATOR


@pytest.mark.django_db
def test_refresh_token(
    dmr_client: DMRClient,
    api_user: object,
) -> None:
    """Refresh endpoint returns a new token pair."""
    login = dmr_client.post(
        reverse('api:core:login'),
        data={'username': 'operator', 'password': 'test-pass'},
    )
    refresh_token = login.json()['refresh_token']

    response = dmr_client.post(
        reverse('api:core:refresh'),
        data={'refresh_token': refresh_token},
    )

    assert response.status_code == HTTPStatus.OK
    parsed = msgspec.convert(response.json(), type=TokenPairPayload)
    assert parsed.access_token
    assert parsed.refresh_token


@pytest.mark.django_db
def test_reviewer_cannot_create_channel(
    dmr_client: DMRClient,
    reviewer_headers: dict[str, str],
) -> None:
    """Reviewers receive 403 when creating channels."""
    from server.apps.channels.models import ChannelKind

    response = dmr_client.post(
        reverse('api:channels_api:channel-collection'),
        data={'name': 'Blocked', 'kind': ChannelKind.CLIPPING},
        headers=reviewer_headers,
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
