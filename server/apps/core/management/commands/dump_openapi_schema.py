"""Dump the merged OpenAPI schema to stdout or a file."""

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from django.test import Client
from django.urls import reverse


class Command(BaseCommand):
    """Write OpenAPI YAML for frontend Orval code generation."""

    help = 'Dump OpenAPI schema as YAML'

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            '--output',
            '-o',
            type=str,
            default='',
            help='Output file path (default: stdout)',
        )

    def handle(self, *args: Any, **options: Any) -> None:
        client = Client()
        response = client.get(reverse('openapi_yaml'))
        text = response.content.decode('utf-8')
        output = str(options.get('output', ''))
        if output:
            Path(output).write_text(text, encoding='utf-8')
            self.stdout.write(self.style.SUCCESS(f'Wrote {output}'))
        else:
            self.stdout.write(text)
