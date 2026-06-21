"""S3-compatible storage backend for library and pipeline assets."""

from typing import Any

import boto3
from botocore.client import BaseClient, Config
from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage
from storages.utils import clean_name


def build_s3_client(endpoint_url: str) -> BaseClient:
    """Return a boto3 S3 client for the given endpoint URL."""
    return boto3.client(
        's3',
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
        verify=getattr(settings, 'AWS_S3_VERIFY', False),
        config=Config(
            signature_version='s3v4',
            s3={'addressing_style': 'path'},
        ),
    )


class AssetStorage(S3Boto3Storage):  # type: ignore[misc]
    """S3-compatible storage for pipeline-generated and library assets."""

    location = 'assets'
    file_overwrite = False
    default_acl = None  # private; access via presigned URLs

    def _public_s3_client(self) -> BaseClient:
        """Return a client that signs URLs for browser-reachable endpoints."""
        client = getattr(self, '_public_client_cache', None)
        if client is None:
            client = build_s3_client(settings.AWS_S3_PUBLIC_ENDPOINT_URL)
            self._public_client_cache = client
        return client

    def url(
        self,
        name: str,
        parameters: dict[str, str] | None = None,
        expire: int | None = None,
        http_method: str | None = None,
    ) -> str:
        """Return a presigned GET URL using the public endpoint when configured."""
        if settings.AWS_S3_PUBLIC_ENDPOINT_URL == settings.AWS_S3_ENDPOINT_URL:
            return super().url(
                name,
                parameters=parameters,
                expire=expire,
                http_method=http_method,
            )

        name = self._normalize_name(clean_name(name))
        params: dict[str, Any] = parameters.copy() if parameters else {}
        if expire is None:
            expire = self.querystring_expire

        params['Bucket'] = self.bucket.name
        params['Key'] = name

        return str(
            self._public_s3_client().generate_presigned_url(
                'get_object',
                Params=params,
                ExpiresIn=expire,
                HttpMethod=http_method,
            ),
        )
