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


@patch('server.common.storage.boto3.client')
def test_init_uses_public_endpoint_for_presigning(
    mock_boto_client: MagicMock,
) -> None:
    """Presigned URLs must use the browser-reachable public endpoint."""
    mock_boto_client.return_value = MagicMock()

    PresignUrlHelper()

    mock_boto_client.assert_called_once()
    call_kwargs = mock_boto_client.call_args.kwargs
    assert call_kwargs['endpoint_url'] == 'http://localhost:9000'
    assert call_kwargs['config'].signature_version == 's3v4'
    assert call_kwargs['config'].s3['addressing_style'] == 'path'
