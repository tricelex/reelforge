"""Presigned URL helpers for S3-compatible storage."""

from typing import final

from django.conf import settings

from server.common.s3 import AssetStorage, build_s3_client


def _storage_object_key(name: str) -> str:
    """Return the bucket object key for a FileField-relative name."""
    location = AssetStorage.location.strip('/')
    if not location or name.startswith(f'{location}/'):
        return name
    return f'{location}/{name}'


@final
class PresignUrlHelper:
    """Generate presigned GET/PUT URLs for RustFS / S3."""

    def __init__(self) -> None:
        """Initialise the boto3 S3 client from Django storage settings."""
        self._bucket = settings.AWS_STORAGE_BUCKET_NAME
        self._client = build_s3_client(settings.AWS_S3_PUBLIC_ENDPOINT_URL)

    def presign_put(
        self,
        key: str,
        content_type: str,
        expires_in: int = 3600,
    ) -> str:
        """Return a presigned PUT URL for uploading an object."""
        _ = content_type  # MIME is recorded at register time, not bound to signature.
        return str(
            self._client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': self._bucket,
                    'Key': _storage_object_key(key),
                },
                ExpiresIn=expires_in,
            ),
        )

    def presign_get(self, key: str, expires_in: int = 3600) -> str:
        """Return a presigned GET URL for downloading an object."""
        return str(
            self._client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self._bucket,
                    'Key': _storage_object_key(key),
                },
                ExpiresIn=expires_in,
            ),
        )
