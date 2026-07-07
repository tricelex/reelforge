"""Tests for channels DMR API."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.channels.models import (
    Channel,
    ChannelKind,
    PublishMode,
    YouTubeCredential,
)


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    return Channel.objects.create(
        name='API Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
    )


@pytest.mark.django_db
def test_list_channels(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.get(
        reverse('api:channels_api:channel-collection'),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['total'] >= 1
    row = next(item for item in body['items'] if item['id'] == str(channel.id))
    assert 'niche_angle' in row
    assert 'published_videos' in row
    assert 'active_runs' in row
    assert 'total_spend_usd' in row
    assert 'youtube_status' in row
    assert row['youtube_status'] == 'disconnected'


@pytest.mark.django_db
def test_create_channel(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.post(
        reverse('api:channels_api:channel-collection'),
        data={
            'name': 'New Channel',
            'kind': ChannelKind.CLIPPING,
        },
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body['name'] == 'New Channel'
    assert Channel.objects.filter(id=body['id']).exists()


@pytest.mark.django_db
def test_create_channel_with_niche(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """POST channel with niche block creates NicheConfig."""
    from server.apps.channels.models import NicheConfig

    response = dmr_client.post(
        reverse('api:channels_api:channel-collection'),
        data={
            'name': 'Niche Channel',
            'kind': ChannelKind.LONGFORM,
            'niche': {
                'angle': 'space exploration',
                'audience': 'sci-fi fans',
            },
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.CREATED
    channel_id = response.json()['id']
    niche = NicheConfig.objects.get(channel_id=channel_id)
    assert niche.angle == 'space exploration'

    niche_resp = dmr_client.get(
        reverse(
            'api:channels_api:channel-niche',
            kwargs={'channel_id': channel_id},
        ),
        headers=auth_headers,
    )
    assert niche_resp.status_code == HTTPStatus.OK
    assert niche_resp.json()['id'] == str(niche.id)
    assert niche_resp.json()['angle'] == 'space exploration'


@pytest.mark.django_db
def test_get_and_patch_channel(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    detail_url = reverse(
        'api:channels_api:channel-detail',
        kwargs={'channel_id': channel.id},
    )
    get_response = dmr_client.get(detail_url, headers=auth_headers)
    assert get_response.status_code == HTTPStatus.OK
    assert get_response.json()['name'] == 'API Channel'

    patch_response = dmr_client.patch(
        detail_url,
        data={'name': 'Renamed Channel', 'wpm': 170},
        headers=auth_headers,
    )
    assert patch_response.status_code == HTTPStatus.OK
    assert patch_response.json()['name'] == 'Renamed Channel'
    assert patch_response.json()['wpm'] == 170


@pytest.mark.django_db
def test_channel_branding_get_and_patch(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    url = reverse(
        'api:channels_api:channel-branding',
        kwargs={'channel_id': channel.id},
    )
    get_response = dmr_client.get(url, headers=auth_headers)
    assert get_response.status_code == HTTPStatus.OK
    assert get_response.json()['channel_id'] == str(channel.id)

    patch_response = dmr_client.patch(
        url,
        data={
            'watermark_position': 'bottom-right',
            'watermark_opacity': 0.8,
            'music_pool_tags': ['ambient'],
        },
        headers=auth_headers,
    )
    assert patch_response.status_code == HTTPStatus.OK
    body = patch_response.json()
    assert body['watermark_position'] == 'bottom-right'
    assert body['music_pool_tags'] == ['ambient']


@pytest.mark.django_db
def test_youtube_connect_requires_redirect_uri(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
    settings,
) -> None:
    settings.YOUTUBE_CLIENT_ID = 'test-client-id'
    url = reverse(
        'api:channels_api:youtube-connect',
        kwargs={'channel_id': channel.id},
    )
    response = dmr_client.get(url, headers=auth_headers)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db
def test_youtube_connect_returns_auth_url(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
    settings,
) -> None:
    settings.YOUTUBE_CLIENT_ID = 'test-client-id'
    url = reverse(
        'api:channels_api:youtube-connect',
        kwargs={'channel_id': channel.id},
    )
    response = dmr_client.get(
        f'{url}?redirect_uri=https://app.example/callback',
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert 'accounts.google.com' in response.json()['authorization_url']


@pytest.mark.django_db
def test_youtube_status_not_connected(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    url = reverse(
        'api:channels_api:youtube-status',
        kwargs={'channel_id': channel.id},
    )
    response = dmr_client.get(url, headers=auth_headers)

    assert response.status_code == HTTPStatus.OK
    assert response.json()['connected'] is False


@pytest.mark.django_db
def test_youtube_callback_stores_credential(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
    settings,
) -> None:
    settings.YOUTUBE_CLIENT_ID = 'test-client-id'
    settings.YOUTUBE_CLIENT_SECRET = 'test-secret'
    url = reverse(
        'api:channels_api:youtube-callback',
        kwargs={'channel_id': channel.id},
    )
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        'access_token': 'access',
        'refresh_token': 'refresh',
        'expires_in': 3600,
        'scope': 'youtube.upload',
    }

    with patch('server.apps.channels.services.httpx.Client') as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = (
            mock_response
        )
        response = dmr_client.post(
            url,
            data={
                'code': 'auth-code',
                'redirect_uri': 'https://app.example/callback',
            },
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['connected'] is True
    assert YouTubeCredential.objects.filter(channel=channel).exists()


@pytest.mark.django_db
def test_get_channel_404(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """GET missing channel returns 404."""
    import uuid

    response = dmr_client.get(
        reverse(
            'api:channels_api:channel-detail',
            kwargs={'channel_id': uuid.uuid4()},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_list_channels_active_filter(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """GET ?active=true returns only active channels."""
    Channel.objects.create(
        name='Inactive Channel',
        kind=ChannelKind.LONGFORM,
        is_active=False,
    )
    active = Channel.objects.create(
        name='Active Channel',
        kind=ChannelKind.LONGFORM,
        is_active=True,
    )

    response = dmr_client.get(
        f'{reverse("api:channels_api:channel-collection")}?active=true',
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    ids = {item['id'] for item in body['items']}
    assert str(active.id) in ids
    assert all(item['is_active'] for item in body['items'])


@pytest.mark.django_db
def test_channel_branding_patch_assets(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """PATCH branding updates intro, fonts, and palette."""
    from server.apps.assets.models import LibraryAsset, LibraryAssetKind

    intro = LibraryAsset.objects.create(
        kind=LibraryAssetKind.INTRO,
        name='Intro',
        file='library/intro.mp4',
    )
    font = LibraryAsset.objects.create(
        kind=LibraryAssetKind.FONT,
        name='Title Font',
        file='library/font.ttf',
    )
    url = reverse(
        'api:channels_api:channel-branding',
        kwargs={'channel_id': channel.id},
    )
    response = dmr_client.patch(
        url,
        data={
            'intro_asset_id': str(intro.id),
            'font_asset_ids': [str(font.id)],
            'thumbnail_palette': {'primary': '#112233', 'accent': '#aabbcc'},
        },
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['intro_asset_id'] == str(intro.id)
    assert body['font_asset_ids'] == [str(font.id)]
    assert body['thumbnail_palette']['primary'] == '#112233'


@pytest.mark.django_db
def test_niche_patch_format_and_banned_topics(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """PATCH niche updates format_id and banned_topics."""
    from server.apps.prompts.models import StoryFormat

    story_format = StoryFormat.objects.create(
        key='selector_format',
        name='Selector Format',
        beats=[],
    )
    url = reverse(
        'api:channels_api:channel-niche',
        kwargs={'channel_id': channel.id},
    )
    response = dmr_client.patch(
        url,
        data={
            'format_id': str(story_format.id),
            'banned_topics': ['politics', 'crypto'],
        },
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['format_id'] == str(story_format.id)
    assert body['banned_topics'] == ['politics', 'crypto']


@pytest.mark.django_db
def test_youtube_connect_without_client_id(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
    settings,
) -> None:
    """YouTube connect without client id returns 422."""
    settings.YOUTUBE_CLIENT_ID = ''
    url = reverse(
        'api:channels_api:youtube-connect',
        kwargs={'channel_id': channel.id},
    )
    response = dmr_client.get(
        f'{url}?redirect_uri=https://app.example/callback',
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db
def test_youtube_callback_errors(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
    settings,
) -> None:
    """YouTube callback surfaces configuration and token exchange failures."""
    url = reverse(
        'api:channels_api:youtube-callback',
        kwargs={'channel_id': channel.id},
    )
    settings.YOUTUBE_CLIENT_ID = ''
    settings.YOUTUBE_CLIENT_SECRET = ''

    missing_config = dmr_client.post(
        url,
        data={'code': 'auth-code', 'redirect_uri': 'https://app.example/cb'},
        headers=auth_headers,
    )
    assert missing_config.status_code == HTTPStatus.BAD_REQUEST

    settings.YOUTUBE_CLIENT_ID = 'test-client-id'
    settings.YOUTUBE_CLIENT_SECRET = 'test-secret'
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {'error': 'invalid_grant'}

    with patch('server.apps.channels.services.httpx.Client') as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = (
            mock_response
        )
        failed = dmr_client.post(
            url,
            data={'code': 'bad-code', 'redirect_uri': 'https://app.example/cb'},
            headers=auth_headers,
        )

    assert failed.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_youtube_status_connected(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """YouTube status reports connected when credential exists."""
    from django.utils import timezone

    YouTubeCredential.objects.create(
        channel=channel,
        access_token='access',
        refresh_token='refresh',
        token_expiry=timezone.now(),
        scope='youtube.upload',
    )
    url = reverse(
        'api:channels_api:youtube-status',
        kwargs={'channel_id': channel.id},
    )
    response = dmr_client.get(url, headers=auth_headers)

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['connected'] is True
    assert body['scope'] == 'youtube.upload'


@pytest.mark.django_db
def test_list_channels_youtube_expired_status(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """Channel list reports expired YouTube tokens."""
    from django.utils import timezone

    YouTubeCredential.objects.create(
        channel=channel,
        access_token='access',
        refresh_token='refresh',
        token_expiry=timezone.now() - timezone.timedelta(hours=1),
        scope='youtube.upload',
    )
    response = dmr_client.get(
        reverse('api:channels_api:channel-collection'),
        headers=auth_headers,
    )
    row = next(
        item
        for item in response.json()['items']
        if item['id'] == str(channel.id)
    )
    assert row['youtube_status'] == 'expired'


@pytest.mark.django_db
def test_list_channels_youtube_connected_status(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """Channel list reports connected YouTube tokens."""
    from django.utils import timezone

    YouTubeCredential.objects.create(
        channel=channel,
        access_token='access',
        refresh_token='refresh',
        token_expiry=timezone.now() + timezone.timedelta(hours=1),
        scope='youtube.upload',
    )
    response = dmr_client.get(
        reverse('api:channels_api:channel-collection'),
        headers=auth_headers,
    )
    row = next(
        item
        for item in response.json()['items']
        if item['id'] == str(channel.id)
    )
    assert row['youtube_status'] == 'connected'


@pytest.fixture
def blueprint(db) -> object:  # type: ignore[no-untyped-def]
    from server.apps.pipelines.models import PipelineBlueprint, PipelineKind

    return PipelineBlueprint.objects.create(
        name='longform_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
        is_active=True,
    )


@pytest.mark.django_db
def test_channel_default_blueprint_get_and_patch(
    dmr_client: DMRClient,
    channel: Channel,
    blueprint: object,
    auth_headers: dict[str, str],
) -> None:
    detail_url = reverse(
        'api:channels_api:channel-detail',
        kwargs={'channel_id': channel.id},
    )
    body = dmr_client.get(detail_url, headers=auth_headers).json()
    assert body['default_blueprint_name'] is None
    assert body['provider_daily_caps'] == []
    assert body['config_overrides'] == {}

    patch_response = dmr_client.patch(
        detail_url,
        data={'default_blueprint_name': 'longform_v1'},
        headers=auth_headers,
    )
    assert patch_response.status_code == HTTPStatus.OK
    assert patch_response.json()['default_blueprint_name'] == 'longform_v1'


@pytest.mark.django_db
def test_channel_patch_invalid_blueprint_returns_400(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    detail_url = reverse(
        'api:channels_api:channel-detail',
        kwargs={'channel_id': channel.id},
    )
    response = dmr_client.patch(
        detail_url,
        data={'default_blueprint_name': 'missing_blueprint'},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_channel_patch_clears_default_blueprint_with_empty_string(
    dmr_client: DMRClient,
    channel: Channel,
    blueprint: object,
    auth_headers: dict[str, str],
) -> None:
    detail_url = reverse(
        'api:channels_api:channel-detail',
        kwargs={'channel_id': channel.id},
    )
    dmr_client.patch(
        detail_url,
        data={'default_blueprint_name': 'longform_v1'},
        headers=auth_headers,
    )
    response = dmr_client.patch(
        detail_url,
        data={'default_blueprint_name': ''},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['default_blueprint_name'] is None


@pytest.mark.django_db
def test_channel_patch_provider_daily_caps(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    detail_url = reverse(
        'api:channels_api:channel-detail',
        kwargs={'channel_id': channel.id},
    )
    response = dmr_client.patch(
        detail_url,
        data={
            'provider_daily_caps': [
                {'provider': 'elevenlabs', 'daily_cap_usd': '25.00'},
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    caps = response.json()['provider_daily_caps']
    assert caps == [{'provider': 'elevenlabs', 'daily_cap_usd': '25.00'}]


@pytest.mark.django_db
def test_channel_patch_rejects_negative_provider_cap(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    detail_url = reverse(
        'api:channels_api:channel-detail',
        kwargs={'channel_id': channel.id},
    )
    response = dmr_client.patch(
        detail_url,
        data={
            'provider_daily_caps': [
                {'provider': 'fal', 'daily_cap_usd': '-1'},
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_channel_patch_rejects_duplicate_provider_cap(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    detail_url = reverse(
        'api:channels_api:channel-detail',
        kwargs={'channel_id': channel.id},
    )
    response = dmr_client.patch(
        detail_url,
        data={
            'provider_daily_caps': [
                {'provider': 'fal', 'daily_cap_usd': '10'},
                {'provider': 'fal', 'daily_cap_usd': '20'},
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_channel_patch_config_overrides(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    detail_url = reverse(
        'api:channels_api:channel-detail',
        kwargs={'channel_id': channel.id},
    )
    response = dmr_client.patch(
        detail_url,
        data={
            'config_overrides': {
                'motion': {'hero_ratio': 0.2},
            },
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['config_overrides'] == {
        'motion': {'hero_ratio': 0.2},
    }


@pytest.mark.django_db
def test_channel_summary_includes_default_blueprint_name(
    dmr_client: DMRClient,
    channel: Channel,
    blueprint: object,
    auth_headers: dict[str, str],
) -> None:
    channel.default_blueprint_name = 'longform_v1'
    channel.save(update_fields=['default_blueprint_name'])
    response = dmr_client.get(
        reverse('api:channels_api:channel-collection'),
        headers=auth_headers,
    )
    row = next(
        item
        for item in response.json()['items']
        if item['id'] == str(channel.id)
    )
    assert row['default_blueprint_name'] == 'longform_v1'


@pytest.mark.django_db
def test_graduation_status_endpoint(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.get(
        reverse(
            'api:channels_api:channel-graduation-status',
            kwargs={'channel_id': str(channel.id)},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['clean_run_count'] == 0
    assert body['required_count'] == 10
    assert body['eligible'] is False


@pytest.mark.django_db
def test_branding_warns_when_identical_to_another_channel(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    from server.apps.channels.models import ChannelBranding

    channel_a = Channel.objects.create(name='Warn A', kind=ChannelKind.LONGFORM)
    channel_b = Channel.objects.create(name='Warn B', kind=ChannelKind.LONGFORM)
    ChannelBranding.objects.create(
        channel=channel_a,
        watermark_position='top_left',
    )
    ChannelBranding.objects.create(
        channel=channel_b,
        watermark_position='top_left',
    )

    response = dmr_client.get(
        reverse(
            'api:channels_api:channel-branding',
            kwargs={'channel_id': str(channel_b.id)},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['warnings']
    assert 'Warn A' in body['warnings'][0]


@pytest.mark.django_db
def test_branding_no_warning_for_default_empty_branding(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """Two channels with no branding set (all-default) should not warn each other."""
    other = Channel.objects.create(name='Other Default', kind=ChannelKind.LONGFORM)
    from server.apps.channels.models import ChannelBranding

    ChannelBranding.objects.create(channel=other)

    response = dmr_client.get(
        reverse(
            'api:channels_api:channel-branding',
            kwargs={'channel_id': str(channel.id)},
        ),
        headers=auth_headers,
    )
    assert response.json()['warnings'] == []
