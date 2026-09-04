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
        {
            'key': 'scene_breakdown',
            'depends_on': ['script'],
            'queue': 'api',
            'config': {
                'min_words': 8,
                'max_words': 16,
                'min_seconds': 3,
                'max_seconds': 5,
                'max_hero_scenes': 6,
            },
        },
        {
            'key': 'script_gate',
            'depends_on': ['scene_breakdown'],
            'gate': True,
            'queue': 'api',
        },
        {
            'key': 'cast_proposal',
            'depends_on': ['scene_breakdown'],
            'queue': 'api',
        },
        {
            'key': 'narrative_qc',
            'depends_on': ['script_gate'],
            'queue': 'api',
        },
        {
            'key': 'character_gate',
            'depends_on': ['cast_proposal', 'narrative_qc'],
            'gate': True,
            'queue': 'api',
        },
        {
            'key': 'visual_prompts',
            'depends_on': ['character_gate'],
            'queue': 'api',
        },
        {
            'key': 'visual_anchors',
            'depends_on': ['visual_prompts'],
            'queue': 'api',
            'config': {'model': 'fal-ai/flux/dev'},
        },
        {
            'key': 'image_gen',
            'depends_on': ['visual_anchors'],
            'queue': 'api',
            'fan_out': 'scenes',
            'config': {
                'model': 'fal-ai/flux/dev',
                'use_character_ref': True,
            },
        },
        {
            'key': 'storyboard_gate',
            'depends_on': ['image_gen'],
            'gate': True,
            'queue': 'api',
        },
        {
            'key': 'tts',
            'depends_on': ['storyboard_gate'],
            'queue': 'api',
            'fan_out': 'chapters',
            'config': {'provider': 'elevenlabs'},
        },
        {
            'key': 'motion',
            'depends_on': ['storyboard_gate'],
            'queue': 'render',
            'fan_out': 'scenes',
            'config': {
                'hero_ratio': 0.15,
                'max_hero_scenes': 6,
                'i2v_enabled': True,
                'i2v_model': (
                    'fal-ai/kling-video/v2.1/standard/image-to-video'
                ),
            },
        },
        {
            'key': 'alignment',
            'depends_on': ['tts', 'scene_breakdown'],
            'queue': 'api',
        },
        {
            'key': 'metadata',
            'depends_on': ['script', 'alignment'],
            'queue': 'api',
        },
        {
            'key': 'thumbnail',
            'depends_on': ['metadata'],
            'queue': 'api',
            'config': {'candidates': 3},
        },
        {
            'key': 'assembly',
            'depends_on': ['motion', 'tts', 'alignment'],
            'queue': 'render',
        },
        {
            'key': 'qc',
            'depends_on': ['assembly'],
            'queue': 'render',
        },
        {
            'key': 'final_gate',
            'depends_on': ['qc', 'thumbnail', 'metadata'],
            'gate': True,
            'queue': 'api',
        },
        {
            'key': 'publish',
            'depends_on': ['final_gate'],
            'queue': 'api',
        },
    ],
}


_LONGFORM_DOC_V1_GRAPH: dict[str, object] = {
    'profile': 'documentary_footage',
    'stages': [
        {'key': 'research', 'depends_on': [], 'queue': 'api'},
        {'key': 'outline', 'depends_on': ['research'], 'queue': 'api'},
        {'key': 'script', 'depends_on': ['outline'], 'queue': 'api'},
        {'key': 'scene_breakdown', 'depends_on': ['script'], 'queue': 'api'},
        {
            'key': 'script_gate',
            'depends_on': ['scene_breakdown'],
            'gate': True,
            'queue': 'api',
        },
        {
            'key': 'narrative_qc',
            'depends_on': ['script_gate'],
            'queue': 'api',
        },
        {
            'key': 'footage_queries',
            'depends_on': ['narrative_qc'],
            'queue': 'api',
        },
        {
            'key': 'footage_search',
            'depends_on': ['footage_queries'],
            'queue': 'api',
            'fan_out': 'scenes',
            'config': {'ai_model': 'fal-ai/flux/dev'},
        },
        {
            'key': 'storyboard_gate',
            'depends_on': ['footage_search'],
            'gate': True,
            'queue': 'api',
        },
        {
            'key': 'tts',
            'depends_on': ['storyboard_gate'],
            'queue': 'api',
            'fan_out': 'chapters',
            'config': {'provider': 'elevenlabs'},
        },
        {
            'key': 'footage_prep',
            'depends_on': ['storyboard_gate'],
            'queue': 'render',
            'fan_out': 'scenes',
            'config': {
                'target_width': 1920,
                'target_height': 1080,
                'fps': 30,
            },
        },
        {
            'key': 'alignment',
            'depends_on': ['tts', 'scene_breakdown'],
            'queue': 'api',
        },
        {
            'key': 'metadata',
            'depends_on': ['script', 'alignment', 'footage_search'],
            'queue': 'api',
        },
        {
            'key': 'thumbnail',
            'depends_on': ['metadata'],
            'queue': 'api',
            'config': {'candidates': 3},
        },
        {
            'key': 'assembly',
            'depends_on': [
                'footage_prep',
                'tts',
                'alignment',
            ],
            'queue': 'render',
        },
        {'key': 'qc', 'depends_on': ['assembly'], 'queue': 'render'},
        {
            'key': 'final_gate',
            'depends_on': ['qc', 'thumbnail', 'metadata'],
            'gate': True,
            'queue': 'api',
        },
        {'key': 'publish', 'depends_on': ['final_gate'], 'queue': 'api'},
    ],
}


def _strip_terminal(
    graph: dict[str, object],
    drop_keys: frozenset[str],
) -> list[dict[str, object]]:
    """Return stage nodes excluding terminal keys (assembly/publish/etc.)."""
    stages: list[dict[str, object]] = graph['stages']  # type: ignore[assignment]
    return [node for node in stages if node['key'] not in drop_keys]


_AUTO_LONGFORM_TERMINAL = frozenset({
    'assembly',
    'qc',
    'final_gate',
    'publish',
})
_AUTO_CLIP_TERMINAL = frozenset({'clip_render', 'clip_distribute'})

_LONGFORM_EDITOR_HANDOFF: list[dict[str, object]] = [
    {
        'key': 'editor_brief',
        'depends_on': [
            'motion',
            'tts',
            'alignment',
            'metadata',
            'thumbnail',
        ],
        'queue': 'api',
    },
    {
        'key': 'timeline_export',
        'depends_on': ['editor_brief'],
        'queue': 'api',
    },
    {
        'key': 'caption_bundle',
        'depends_on': ['timeline_export'],
        'queue': 'api',
    },
    {
        'key': 'package_zip',
        'depends_on': ['caption_bundle'],
        'queue': 'render',
    },
]

_LONGFORM_DOC_EDITOR_HANDOFF: list[dict[str, object]] = [
    {
        'key': 'editor_brief',
        'depends_on': [
            'footage_prep',
            'tts',
            'alignment',
            'metadata',
            'thumbnail',
        ],
        'queue': 'api',
    },
    {
        'key': 'timeline_export',
        'depends_on': ['editor_brief'],
        'queue': 'api',
    },
    {
        'key': 'caption_bundle',
        'depends_on': ['timeline_export'],
        'queue': 'api',
    },
    {
        'key': 'package_zip',
        'depends_on': ['caption_bundle'],
        'queue': 'render',
    },
]

_CLIPPING_EDITOR_HANDOFF: list[dict[str, object]] = [
    {
        'key': 'editor_brief',
        'depends_on': ['clip_approval_gate'],
        'queue': 'api',
    },
    {
        'key': 'timeline_export',
        'depends_on': ['editor_brief'],
        'queue': 'api',
    },
    {
        'key': 'caption_bundle',
        'depends_on': ['timeline_export'],
        'queue': 'api',
    },
    {
        'key': 'package_zip',
        'depends_on': ['caption_bundle'],
        'queue': 'render',
    },
]

_LONGFORM_EDITOR_V1_GRAPH: dict[str, object] = {
    'handoff': 'editor_package',
    'stages': (
        _strip_terminal(_LONGFORM_V1_GRAPH, _AUTO_LONGFORM_TERMINAL)
        + _LONGFORM_EDITOR_HANDOFF
    ),
}

_LONGFORM_DOC_EDITOR_V1_GRAPH: dict[str, object] = {
    'handoff': 'editor_package',
    'profile': 'documentary_footage',
    'stages': (
        _strip_terminal(_LONGFORM_DOC_V1_GRAPH, _AUTO_LONGFORM_TERMINAL)
        + _LONGFORM_DOC_EDITOR_HANDOFF
    ),
}

_CLIPPING_EDITOR_V1_GRAPH: dict[str, object] = {
    'handoff': 'editor_package',
    'stages': (
        _strip_terminal(_CLIPPING_V1_GRAPH, _AUTO_CLIP_TERMINAL)
        + _CLIPPING_EDITOR_HANDOFF
    ),
}

_CLIPPING_EDITOR_MANUAL_V1_GRAPH: dict[str, object] = {
    'handoff': 'editor_package',
    'stages': (
        _strip_terminal(_CLIPPING_V1_MANUAL_GRAPH, _AUTO_CLIP_TERMINAL)
        + _CLIPPING_EDITOR_HANDOFF
    ),
}


class Command(BaseCommand):
    """Seed pipeline blueprints (idempotent upsert)."""

    help = (
        'Seed pipeline blueprints (longform, documentary, clipping, '
        'editor handoff, idempotent)'
    )

    @override
    def handle(self, *args: object, **options: object) -> None:
        """Create or update longform, documentary, clipping, editor blueprints."""
        from server.apps.pipelines.models import (  # noqa: PLC0415
            PipelineBlueprint,
            PipelineKind,
        )

        specs = [
            ('longform_v1', PipelineKind.LONGFORM, _LONGFORM_V1_GRAPH),
            (
                'longform_documentary_v1',
                PipelineKind.LONGFORM,
                _LONGFORM_DOC_V1_GRAPH,
            ),
            ('clipping_v1', PipelineKind.CLIPPING, _CLIPPING_V1_GRAPH),
            (
                'clipping_v1_manual',
                PipelineKind.CLIPPING,
                _CLIPPING_V1_MANUAL_GRAPH,
            ),
            (
                'longform_editor_v1',
                PipelineKind.LONGFORM,
                _LONGFORM_EDITOR_V1_GRAPH,
            ),
            (
                'longform_doc_editor_v1',
                PipelineKind.LONGFORM,
                _LONGFORM_DOC_EDITOR_V1_GRAPH,
            ),
            (
                'clipping_editor_v1',
                PipelineKind.CLIPPING,
                _CLIPPING_EDITOR_V1_GRAPH,
            ),
            (
                'clipping_editor_manual_v1',
                PipelineKind.CLIPPING,
                _CLIPPING_EDITOR_MANUAL_V1_GRAPH,
            ),
        ]
        for name, kind, graph in specs:
            bp, created = PipelineBlueprint.objects.update_or_create(
                name=name,
                kind=kind,
                defaults={'graph': graph, 'is_active': True},
            )
            action = 'Created' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'{action} blueprint: {bp}'))
