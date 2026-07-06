"""Seed pipeline blueprints (idempotent)."""

from typing import override

from django.core.management.base import BaseCommand

_CLIPPING_V1_GRAPH: dict[str, object] = {
    'stages': [
        {'key': 'clip_ingest', 'depends_on': []},
        {'key': 'clip_transcribe', 'depends_on': ['clip_ingest']},
        {
            'key': 'clip_analyze',
            'depends_on': ['clip_transcribe'],
            'config': {'clips_requested': 5},
        },
        {
            'key': 'clip_approval_gate',
            'depends_on': ['clip_analyze'],
            'gate': True,
        },
        {'key': 'clip_render', 'depends_on': ['clip_approval_gate']},
        {'key': 'clip_distribute', 'depends_on': ['clip_render']},
    ],
}

_CLIPPING_V1_MANUAL_GRAPH: dict[str, object] = {
    'stages': [
        {'key': 'clip_ingest', 'depends_on': []},
        {'key': 'clip_transcribe', 'depends_on': ['clip_ingest']},
        {'key': 'clip_manual_setup', 'depends_on': ['clip_transcribe']},
        {
            'key': 'clip_approval_gate',
            'depends_on': ['clip_manual_setup'],
            'gate': True,
        },
        {'key': 'clip_render', 'depends_on': ['clip_approval_gate']},
        {'key': 'clip_distribute', 'depends_on': ['clip_render']},
    ],
}

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
    """Seed pipeline blueprints (idempotent upsert)."""

    help = 'Seed pipeline blueprints (longform + clipping, idempotent)'

    @override
    def handle(self, *args: object, **options: object) -> None:
        """Create or update the longform_v1 and clipping_v1* blueprints."""
        from server.apps.pipelines.models import (  # noqa: PLC0415
            PipelineBlueprint,
            PipelineKind,
        )

        specs = [
            ('longform_v1', PipelineKind.LONGFORM, _LONGFORM_V1_GRAPH),
            ('clipping_v1', PipelineKind.CLIPPING, _CLIPPING_V1_GRAPH),
            ('clipping_v1_manual', PipelineKind.CLIPPING, _CLIPPING_V1_MANUAL_GRAPH),
        ]
        for name, kind, graph in specs:
            bp, created = PipelineBlueprint.objects.update_or_create(
                name=name,
                kind=kind,
                defaults={'graph': graph, 'is_active': True},
            )
            action = 'Created' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'{action} blueprint: {bp}'))
