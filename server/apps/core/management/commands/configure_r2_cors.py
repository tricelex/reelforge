"""Set CORS policy on the R2 bucket so browsers can load static files."""

import json
from argparse import ArgumentParser

from django.conf import settings
from django.core.management.base import BaseCommand

from server.common.s3 import build_s3_client


class Command(BaseCommand):
    help = 'Configure CORS policy on the R2/S3 storage bucket.'

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            '--origins',
            nargs='+',
            default=[f'https://{settings.ALLOWED_HOSTS[0]}'],
            help='Space-separated allowed origins.',
        )

    def handle(self, **options: object) -> None:
        origins: list[str] = options['origins']  # type: ignore[assignment]
        client = build_s3_client(settings.AWS_S3_ENDPOINT_URL)
        bucket = settings.AWS_STORAGE_BUCKET_NAME

        cors_config = {
            'CORSRules': [
                {
                    'AllowedOrigins': origins,
                    'AllowedMethods': ['GET', 'HEAD'],
                    'AllowedHeaders': ['*'],
                    'ExposeHeaders': [],
                    'MaxAgeSeconds': 86400,
                }
            ]
        }

        client.put_bucket_cors(
            Bucket=bucket,
            CORSConfiguration=cors_config,
        )

        self.stdout.write(
            f'CORS policy set on bucket "{bucket}":\n'
            + json.dumps(cors_config, indent=2)
        )
