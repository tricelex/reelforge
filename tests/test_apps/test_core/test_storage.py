"""Tests for PresignUrlHelper."""

from unittest.mock import MagicMock, patch

from server.common.storage import PresignUrlHelper


def test_presign_put_returns_url() -> None:
    """presign_put delegates to boto3 generate_presigned_url."""
    helper = PresignUrlHelper.__new__(PresignUrlHelper)
    helper._bucket = 'test-bucket'
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = 'https://example/put'
    helper._client = mock_client

    url = helper.presign_put('assets/foo.mp4', 'video/mp4', expires_in=600)

    assert url == 'https://example/put'
    mock_client.generate_presigned_url.assert_called_once()


def test_presign_get_returns_url() -> None:
    """presign_get delegates to boto3 generate_presigned_url."""
    helper = PresignUrlHelper.__new__(PresignUrlHelper)
    helper._bucket = 'test-bucket'
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = 'https://example/get'
    helper._client = mock_client

    url = helper.presign_get('assets/foo.mp4', expires_in=300)

    assert url == 'https://example/get'
    mock_client.generate_presigned_url.assert_called_once()


def test_storage_object_key_prefixes_asset_location() -> None:
    """FileField names map to S3 keys under the assets/ storage prefix."""
    from server.common.storage import _storage_object_key

    assert _storage_object_key('library/foo.png') == (
        'assets/library/foo.png'
    )
    assert _storage_object_key('assets/library/foo.png') == (
        'assets/library/foo.png'
    )


def test_presign_put_uses_storage_object_key() -> None:
    """presign_put signs the bucket key including the storage location."""
    helper = PresignUrlHelper.__new__(PresignUrlHelper)
    helper._bucket = 'test-bucket'
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = 'https://example/put'
    helper._client = mock_client

    helper.presign_put('library/foo.png', 'image/png')

    params = mock_client.generate_presigned_url.call_args.kwargs['Params']
    assert params['Key'] == 'assets/library/foo.png'
    assert 'ContentType' not in params


@patch('server.common.storage.build_s3_client')
def test_init_uses_public_endpoint_for_presigning(
    mock_build_client: MagicMock,
) -> None:
    """Presigned URLs must use the browser-reachable public endpoint."""
    mock_build_client.return_value = MagicMock()

    PresignUrlHelper()

    mock_build_client.assert_called_once_with('http://localhost:9000')


@patch('server.common.s3.build_s3_client')
def test_asset_storage_url_uses_public_endpoint(
    mock_build_client: MagicMock,
) -> None:
    """Admin file links must be signed for the browser-reachable endpoint."""
    from django.test.utils import override_settings

    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = (
        'http://localhost:9000/reelforge/assets/renditions/foo.mp4?sig=1'
    )
    mock_build_client.return_value = mock_client

    with override_settings(
        AWS_S3_ENDPOINT_URL='http://rustfs:9000',
        AWS_S3_PUBLIC_ENDPOINT_URL='http://localhost:9000',
        AWS_STORAGE_BUCKET_NAME='reelforge',
    ):
        from server.common.s3 import AssetStorage

        storage = AssetStorage()
        storage._bucket = MagicMock()
        storage._bucket.name = 'reelforge'

        url = storage.url('renditions/foo.mp4')

    assert url.startswith('http://localhost:9000/')
    mock_build_client.assert_called_once_with('http://localhost:9000')
    mock_client.generate_presigned_url.assert_called_once()
    params = mock_client.generate_presigned_url.call_args.kwargs['Params']
    assert params['Bucket'] == 'reelforge'
    assert params['Key'] == 'assets/renditions/foo.mp4'
