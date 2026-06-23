"""Seed the longform_v1 pipeline blueprint (idempotent)."""

from typing import override

from django.core.management.base import BaseCommand

_LONGFORM_V1_GRAPH: dict[str, object] = {
    'stages': [
        {'key': 'research', 'depends_on': [], 'queue': 'api'},
        {'key': 'outline', 'depends_on': ['research'], 'queue': 'api'},
        {'key': 'script', 'depends_on': ['outline'], 'queue': 'api'},
        {'key': 'scene_breakdown', 'depends_on': ['script'], 'queue': 'api'},
        {
            'key': 'visual_prompts',
            'depends_on': ['scene_breakdown'],
            'queue': 'api',
        },
        {
            'key': 'image_gen',
            'depends_on': ['visual_prompts'],
            'queue': 'api',
            'fan_out': 'scenes',
            'config': {
                'model': 'fal-ai/flux-kontext-pro',
                'use_character_ref': True,
            },
        },
        {
            'key': 'tts',
            'depends_on': ['scene_breakdown'],
            'queue': 'api',
            'fan_out': 'chapters',
            'config': {'provider': 'elevenlabs'},
        },
        {
            'key': 'motion',
            'depends_on': ['image_gen'],
            'queue': 'render',
            'fan_out': 'scenes',
            'config': {
                'hero_ratio': 0.15,
                'i2v_model': 'fal-ai/kling-video/v2.1/standard/image-to-video',
            },
        },
        {'key': 'alignment', 'depends_on': ['tts'], 'queue': 'gpu'},
        {
            'key': 'music_plan',
            'depends_on': ['scene_breakdown'],
            'queue': 'api',
        },
        {
            'key': 'thumbnail',
            'depends_on': ['script'],
            'queue': 'api',
            'config': {'candidates': 3},
        },
        {
            'key': 'metadata',
            'depends_on': ['script', 'alignment'],
            'queue': 'api',
        },
        {
            'key': 'assembly',
            'depends_on': ['motion', 'tts', 'alignment', 'music_plan'],
            'queue': 'render',
        },
        {
            'key': 'qc',
            'depends_on': ['assembly'],
            'queue': 'render',
        },
    ],
}


class Command(BaseCommand):
    """Seed the longform_v1 pipeline blueprint (idempotent upsert)."""

    help = 'Seed the longform_v1 pipeline blueprint (idempotent)'

    @override
    def handle(self, *args: object, **options: object) -> None:
        """Create or update the longform_v1 blueprint."""
        from server.apps.pipelines.models import (  # noqa: PLC0415
            PipelineBlueprint,
            PipelineKind,
        )

        bp, created = PipelineBlueprint.objects.update_or_create(
            name='longform_v1',
            kind=PipelineKind.LONGFORM,
            defaults={
                'graph': _LONGFORM_V1_GRAPH,
                'is_active': True,
            },
        )
        action = 'Created' if created else 'Updated'
        self.stdout.write(self.style.SUCCESS(f'{action} blueprint: {bp}'))
