"""Tests for the enums API."""

from http import HTTPStatus

import msgspec
import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.core.logic.value_objects import EnumsPayload


@pytest.mark.django_db
def test_enums_requires_auth(dmr_client: DMRClient) -> None:
    """Enums endpoint returns 401 without token."""
    response = dmr_client.get(reverse('api:core_enums:enums'))
    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
def test_enums_returns_registry(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """Enums endpoint returns TextChoices registry."""
    response = dmr_client.get(
        reverse('api:core_enums:enums'),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    parsed = msgspec.convert(response.json(), type=EnumsPayload)
    assert 'RunStatus' in parsed.enums
    assert 'ChannelResearchStatus' in parsed.enums
    assert 'ChannelResearchKind' in parsed.enums
    assert 'VisualMedium' in parsed.enums
    assert 'CandidateStatus' in parsed.enums
    assert len(parsed.enums['RunStatus']) > 0
