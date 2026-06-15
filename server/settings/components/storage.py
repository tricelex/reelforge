from server.settings.components import config

# RustFS / MinIO / S3-compatible object storage
AWS_ACCESS_KEY_ID: str = config('AWS_ACCESS_KEY_ID', default='minioadmin')
AWS_SECRET_ACCESS_KEY: str = config(
    'AWS_SECRET_ACCESS_KEY',
    default='minioadmin',
)
AWS_STORAGE_BUCKET_NAME: str = config(
    'AWS_STORAGE_BUCKET_NAME',
    default='reelforge',
)
AWS_S3_ENDPOINT_URL: str = config(
    'AWS_S3_ENDPOINT_URL',
    default='http://rustfs:9000',
)
AWS_S3_REGION_NAME: str = config('AWS_S3_REGION_NAME', default='us-east-1')
AWS_S3_FILE_OVERWRITE: bool = False
AWS_DEFAULT_ACL: str | None = None
# Disable SSL cert verification for local dev (set True in prod)
AWS_S3_VERIFY: bool = config('AWS_S3_VERIFY', default=False, cast=bool)

STORAGES: dict[str, dict[str, str]] = {
    'default': {'BACKEND': 'server.common.s3.AssetStorage'},
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}
