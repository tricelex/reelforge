from storages.backends.s3boto3 import S3Boto3Storage


class AssetStorage(S3Boto3Storage):
    """S3-compatible storage for pipeline-generated and library assets."""

    location = 'assets'
    file_overwrite = False
    default_acl = None  # private; access via presigned URLs
