"""Tests for assets DMR API."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.assets.models import LibraryAssetKind
from server.common.storage import PresignUrlHelper


@pytest.mark.django_db
def test_presign_upload(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """POST presign returns a PUT URL and storage key."""
    mock_presign = MagicMock()
    mock_presign.presign_put.return_value = 'https://storage.example/put'
    with patch.object(
        PresignUrlHelper,
        'presign_put',
        mock_presign.presign_put,
    ):
        response = dmr_client.post(
            reverse('api:assets_api:upload-presign'),
            data={'filename': 'clip.mp4', 'mime': 'video/mp4'},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['url'] == 'https://storage.example/put'
    assert body['key'].startswith('library/')


@pytest.mark.django_db
def test_library_asset_register_and_list(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    create_response = dmr_client.post(
        reverse('api:assets_api:library-asset-collection'),
        data={
            'kind': LibraryAssetKind.MUSIC,
            'name': 'API Track',
            'storage_key': 'uploads/test/track.mp3',
            'tags': ['test'],
        },
        headers=auth_headers,
    )
    assert create_response.status_code == HTTPStatus.CREATED
    asset_id = create_response.json()['id']

    list_response = dmr_client.get(
        reverse('api:assets_api:library-asset-collection'),
        headers=auth_headers,
    )
    assert list_response.status_code == HTTPStatus.OK
    assert list_response.json()['total'] >= 1

    detail_response = dmr_client.get(
        reverse(
            'api:assets_api:library-asset-detail',
            kwargs={'asset_id': asset_id},
        ),
        headers=auth_headers,
    )
    assert detail_response.status_code == HTTPStatus.OK
    detail_body = detail_response.json()
    assert detail_body['name'] == 'API Track'
    assert detail_body['url'].startswith('http')
    assert detail_body['mime'] == 'audio/mpeg'


@pytest.mark.django_db
def test_library_asset_detail_includes_presigned_url(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """GET detail returns a presigned URL for preview."""
    create_response = dmr_client.post(
        reverse('api:assets_api:library-asset-collection'),
        data={
            'kind': LibraryAssetKind.MUSIC,
            'name': 'Preview Track',
            'storage_key': 'uploads/test/preview.mp3',
        },
        headers=auth_headers,
    )
    asset_id = create_response.json()['id']
    mock_presign = MagicMock()
    mock_presign.presign_get.return_value = 'https://storage.example/preview.mp3'
    with patch.object(
        PresignUrlHelper,
        'presign_get',
        mock_presign.presign_get,
    ):
        detail_response = dmr_client.get(
            reverse(
                'api:assets_api:library-asset-detail',
                kwargs={'asset_id': asset_id},
            ),
            headers=auth_headers,
        )

    assert detail_response.status_code == HTTPStatus.OK
    detail = detail_response.json()
    assert detail['url'] == 'https://storage.example/preview.mp3'
    assert detail['mime'] == 'audio/mpeg'
    mock_presign.presign_get.assert_called_once_with('uploads/test/preview.mp3')


@pytest.mark.django_db
def test_library_asset_detail_404(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """GET missing library asset returns 404."""
    import uuid

    response = dmr_client.get(
        reverse(
            'api:assets_api:library-asset-detail',
            kwargs={'asset_id': uuid.uuid4()},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
