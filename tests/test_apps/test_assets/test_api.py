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
    assert body['key'].startswith('uploads/')


@pytest.mark.django_db
def test_library_asset_register_and_list(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    def _noop_async_to_sync(func):  # type: ignore[no-untyped-def]
        def _wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
            return None

        return _wrapper

    with patch(
        'server.apps.assets.tasks.async_to_sync',
        _noop_async_to_sync,
    ):
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
    assert detail_response.json()['name'] == 'API Track'


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
