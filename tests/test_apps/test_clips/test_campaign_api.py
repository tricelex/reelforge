"""Tests for clip campaign and earnings API."""

import uuid
from http import HTTPStatus

import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.channels.models import Channel, ChannelKind
from server.apps.clips.logic.constants import CampaignStatus
from server.apps.clips.models import ClipCampaign, Earning


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    """Clipping channel for campaign tests."""
    return Channel.objects.create(
        name='Campaign Channel',
        kind=ChannelKind.CLIPPING,
    )


@pytest.mark.django_db
def test_campaign_crud(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """Create, list, and patch a clip campaign."""
    create_resp = dmr_client.post(
        reverse('api:clips:campaign-collection'),
        data={
            'channel_id': str(channel.id),
            'name': 'Q3 podcast clips',
            'notes': 'Batch export',
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == HTTPStatus.CREATED
    campaign_id = create_resp.json()['id']

    list_resp = dmr_client.get(
        reverse('api:clips:campaign-collection'),
        headers=auth_headers,
    )
    assert list_resp.status_code == HTTPStatus.OK
    assert list_resp.json()['total'] == 1

    patch_resp = dmr_client.patch(
        reverse(
            'api:clips:campaign-detail',
            kwargs={'campaign_id': campaign_id},
        ),
        data={'status': CampaignStatus.ACTIVE},
        headers=auth_headers,
    )
    assert patch_resp.status_code == HTTPStatus.OK
    assert patch_resp.json()['status'] == CampaignStatus.ACTIVE


@pytest.mark.django_db
def test_campaign_patch_not_found(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """PATCH missing campaign returns 404."""
    response = dmr_client.patch(
        reverse(
            'api:clips:campaign-detail',
            kwargs={'campaign_id': uuid.uuid4()},
        ),
        data={'status': CampaignStatus.ACTIVE},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_earning_create_and_list(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """Record and list manual earnings for a campaign."""
    campaign = ClipCampaign.objects.create(
        channel=channel,
        name='Earnings test',
    )

    create_resp = dmr_client.post(
        reverse('api:clips:earning-collection'),
        data={
            'campaign_id': str(campaign.id),
            'platform': 'youtube',
            'revenue_est_usd': '12.5000',
            'recorded_at': '2026-06-19T12:00:00+00:00',
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == HTTPStatus.CREATED

    list_resp = dmr_client.get(
        reverse('api:clips:earning-collection'),
        query_params={'campaign': str(campaign.id)},
        headers=auth_headers,
    )
    assert list_resp.status_code == HTTPStatus.OK
    assert list_resp.json()['total'] == 1
    assert Earning.objects.filter(campaign=campaign).count() == 1


@pytest.mark.django_db
def test_get_campaign_detail(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """GET campaign detail returns one campaign."""
    campaign = ClipCampaign.objects.create(
        channel=channel,
        name='Detail campaign',
    )

    response = dmr_client.get(
        reverse(
            'api:clips:campaign-detail',
            kwargs={'campaign_id': campaign.id},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['name'] == 'Detail campaign'


@pytest.mark.django_db
def test_campaign_not_found(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """GET and PATCH return 404 for unknown campaigns."""
    detail_url = reverse(
        'api:clips:campaign-detail',
        kwargs={'campaign_id': uuid.uuid4()},
    )

    get_resp = dmr_client.get(detail_url, headers=auth_headers)
    assert get_resp.status_code == HTTPStatus.NOT_FOUND

    patch_resp = dmr_client.patch(
        detail_url,
        data={'name': 'Nope'},
        headers=auth_headers,
    )
    assert patch_resp.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_campaign_patch_invalid_status(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """PATCH campaign with invalid status returns 422."""
    campaign = ClipCampaign.objects.create(
        channel=channel,
        name='Status test',
    )

    response = dmr_client.patch(
        reverse(
            'api:clips:campaign-detail',
            kwargs={'campaign_id': campaign.id},
        ),
        data={'status': 'INVALID'},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db
def test_earning_bad_campaign_id(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """POST earning with unknown campaign returns 404."""
    response = dmr_client.post(
        reverse('api:clips:earning-collection'),
        data={
            'campaign_id': str(uuid.uuid4()),
            'platform': 'youtube',
            'revenue_est_usd': '1.0000',
            'recorded_at': '2026-06-19T12:00:00+00:00',
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_list_campaigns_channel_filter(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """GET campaigns filters by channel_id."""
    other = Channel.objects.create(
        name='Other campaign channel',
        kind=ChannelKind.CLIPPING,
    )
    ClipCampaign.objects.create(channel=channel, name='Mine')
    ClipCampaign.objects.create(channel=other, name='Theirs')

    response = dmr_client.get(
        f'{reverse("api:clips:campaign-collection")}?channel_id={channel.id}',
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['total'] == 1
    assert body['items'][0]['name'] == 'Mine'


@pytest.mark.django_db
def test_earning_naive_recorded_at(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """POST earning accepts naive recorded_at timestamps."""
    campaign = ClipCampaign.objects.create(
        channel=channel,
        name='Naive datetime',
    )

    response = dmr_client.post(
        reverse('api:clips:earning-collection'),
        data={
            'campaign_id': str(campaign.id),
            'platform': 'tiktok',
            'revenue_est_usd': '3.2500',
            'recorded_at': '2026-06-19T12:00:00',
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.CREATED
    assert 'recorded_at' in response.json()
