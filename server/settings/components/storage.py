from server.settings.components import config

# S3-compatible object storage (RustFS in dev, Cloudflare R2 in production)
AWS_ACCESS_KEY_ID: str = config('AWS_ACCESS_KEY_ID', default='minioadmin')
AWS_SECRET_ACCESS_KEY: str = config(
    'AWS_SECRET_ACCESS_KEY',
    default='minioadmin',
)
AWS_STORAGE_BUCKET_NAME: str = config(
    'AWS_STORAGE_BUCKET_NAME',
    default='***REMOVED***',
)
AWS_S3_ENDPOINT_URL: str = config(
    'AWS_S3_ENDPOINT_URL',
    default='http://rustfs:9000',
)
# Browser-facing endpoint for presigned URLs. In Docker dev, rustfs is only
# reachable on the backend network; clients use localhost via compose ports.
# In production, set to the R2 account endpoint.
AWS_S3_PUBLIC_ENDPOINT_URL: str = config(
    'AWS_S3_PUBLIC_ENDPOINT_URL',
    default='http://localhost:9000',
)
AWS_S3_REGION_NAME: str = config('AWS_S3_REGION_NAME', default='us-east-1')
AWS_S3_FILE_OVERWRITE: bool = False
AWS_DEFAULT_ACL: str | None = None
# Set True in production (R2 has valid TLS certs; local RustFS does not)
AWS_S3_VERIFY: bool = config('AWS_S3_VERIFY', default=False, cast=bool)
# Public domain for static files (R2 custom domain or pub-xxx.r2.dev URL).
# Leave empty in local dev — static files are served from the local filesystem.
AWS_S3_CUSTOM_DOMAIN: str = config('AWS_S3_CUSTOM_DOMAIN', default='')

STORAGES: dict[str, dict[str, str]] = {
    'default': {'BACKEND': 'server.common.s3.AssetStorage'},
    'staticfiles': {'BACKEND': 'server.common.s3.StaticStorage'},
}
