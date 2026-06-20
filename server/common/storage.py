"""Presigned URL helpers for S3-compatible storage."""

from typing import final

import boto3
from botocore.client import Config
from django.conf import settings


@final
class PresignUrlHelper:
    """Generate presigned GET/PUT URLs for RustFS / S3."""

    def __init__(self) -> None:
        """Initialise the boto3 S3 client from Django storage settings."""
        self._bucket = settings.AWS_STORAGE_BUCKET_NAME
        self._client = boto3.client(
            's3',
            endpoint_url=settings.AWS_S3_PUBLIC_ENDPOINT_URL,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME,
            verify=getattr(settings, 'AWS_S3_VERIFY', False),
            config=Config(
                signature_version='s3v4',
                s3={'addressing_style': 'path'},
            ),
        )

    def presign_put(
        self,
        key: str,
        content_type: str,
        expires_in: int = 3600,
    ) -> str:
        """Return a presigned PUT URL for uploading an object."""
        return str(
            self._client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': self._bucket,
                    'Key': key,
                    'ContentType': content_type,
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
                    'Key': key,
                },
                ExpiresIn=expires_in,
            ),
        )
