"""Tests for footage sourcing config on the channels DMR API."""

from http import HTTPStatus

import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.channels.models import (
    Channel,
    ChannelKind,
    FootageSourcingConfig,
)


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    return Channel.objects.create(name='Doc Channel', kind=ChannelKind.LONGFORM)


@pytest.mark.django_db
def test_channel_detail_includes_footage_sourcing_defaults(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """A channel with no config row returns defaults, not null."""
    detail_url = reverse(
        'api:channels_api:channel-detail',
        kwargs={'channel_id': channel.id},
    )

    response = dmr_client.get(detail_url, headers=auth_headers)

    assert response.status_code == HTTPStatus.OK
    body = response.json()['footage_sourcing']
    assert body is not None
    assert body['enabled_providers'] == [
        'pexels',
        'pixabay',
        'wikimedia',
        'openverse',
        'archive_org',
    ]
    assert body['sourcing_mode'] == 'stock_first'
    assert body['ai_fallback_enabled'] is True
    assert body['rerank_mode'] == 'vision'
    assert body['candidates_per_scene'] == 8
    assert body['min_clip_width'] == 1280
    assert body['min_clip_duration_s'] == pytest.approx(3.0)
    assert body['allowed_licenses'] == []
    assert body['require_attribution'] is True


@pytest.mark.django_db
def test_patch_creates_the_config_row(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """PATCH with a footage_sourcing body creates the row."""
    detail_url = reverse(
        'api:channels_api:channel-detail',
        kwargs={'channel_id': channel.id},
    )
    assert not FootageSourcingConfig.objects.filter(channel=channel).exists()

    response = dmr_client.patch(
        detail_url,
        data={
            'footage_sourcing': {
                'sourcing_mode': 'archival_first',
                'ai_fallback_enabled': False,
                'candidates_per_scene': 12,
            },
        },
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()['footage_sourcing']
    assert body['sourcing_mode'] == 'archival_first'
    assert body['ai_fallback_enabled'] is False
    assert body['candidates_per_scene'] == 12
    config = FootageSourcingConfig.objects.get(channel=channel)
    assert config.sourcing_mode == 'archival_first'
    assert config.ai_fallback_enabled is False
    assert config.candidates_per_scene == 12


@pytest.mark.django_db
def test_patch_preserves_provider_order(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """enabled_providers is an ordered priority list, not a set."""
    detail_url = reverse(
        'api:channels_api:channel-detail',
        kwargs={'channel_id': channel.id},
    )

    response = dmr_client.patch(
        detail_url,
        data={
            'footage_sourcing': {
                'enabled_providers': ['wikimedia', 'openverse', 'pexels'],
            },
        },
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()['footage_sourcing']
    assert body['enabled_providers'] == ['wikimedia', 'openverse', 'pexels']

    get_response = dmr_client.get(detail_url, headers=auth_headers)
    assert get_response.json()['footage_sourcing']['enabled_providers'] == [
        'wikimedia',
        'openverse',
        'pexels',
    ]


@pytest.mark.django_db
def test_patch_rejects_an_unknown_rerank_mode(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """An unknown rerank_mode is rejected with a 400."""
    detail_url = reverse(
        'api:channels_api:channel-detail',
        kwargs={'channel_id': channel.id},
    )

    response = dmr_client.patch(
        detail_url,
        data={'footage_sourcing': {'rerank_mode': 'not_a_mode'}},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert not FootageSourcingConfig.objects.filter(channel=channel).exists()
