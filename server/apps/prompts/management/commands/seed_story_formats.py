"""Seed documentary story formats and their prompt templates (idempotent)."""

from typing import override

from django.core.management.base import BaseCommand

_DOC_BEATS = [
    'cold_open_hook',
    'thesis',
    'context',
    'escalating_evidence',
    'turn',
    'resolution',
    'reflection',
]

_SCRIPT_SYSTEM = (
    'You write narration for documentary videos built from stock and '
    'archival footage. Narration may name specific people, places, and '
    'dates. The VISUALS may not: every scene must be describable as an '
    'archetypal, findable shot. Write "a destroyer\'s deck in heavy seas", '
    'never "HMS Hood at 05:52". Favour visual motifs that recur across the '
    'video — maps, documents, machinery, landscapes, crowds, hands at work '
    '— so a limited footage inventory carries the full runtime without '
    'visible repetition. Never describe a shot that could only exist if '
    'someone had filmed one specific unrepeatable moment.'
)

_SCRIPT_USER = (
    'Write the documentary script for "{{ topic }}".\n'
    'Audience: {{ niche.audience }}\n'
    'Angle: {{ niche.angle }}\n'
    'Research: {{ upstream.research }}\n'
    'Outline: {{ upstream.outline }}\n'
    'Every visual you imply must be sourceable from a footage library.'
)

_BREAKDOWN_SYSTEM = (
    'You break documentary scripts into scenes for footage sourcing. Each '
    'scene needs 6-12 seconds of narration and a visual_concept naming a '
    'concrete, generic, findable shot. Set era_hint for period material and '
    'avoid anachronism — do not pair 1940s narration with a visual concept '
    'that implies modern equipment. This format has no cast: return an '
    'empty cast list. Each scene narration_text must be 10-35 words and a '
    'contiguous verbatim slice covering the chapter. Keep setting stable '
    'across adjacent scenes in one location.'
)

_BREAKDOWN_USER = (
    'Break "{{ topic }}" into documentary scenes.\n'
    'Chapters: {{ upstream.script.chapters }}\n'
    'Return scenes with idx, chapter_idx, beat, narration_text, '
    'visual_concept, shot_type, est_seconds (6-12), is_hero, word_count. '
    'Return an empty cast list.'
)

_QUERIES_SYSTEM = (
    'You write search queries for stock and public-domain footage '
    'libraries. For each scene, produce a primary_query of 2-5 concrete '
    'visual nouns describing an archetypal, findable shot. Never name '
    'individuals or specific dated events. Add 2-3 progressively broader '
    'fallback_queries. Set media_preference to "video" for motion-led '
    'scenes and "image" for archival or static ones. Always write an '
    'ai_fallback_prompt used only when no footage is found.'
)

_QUERIES_USER = (
    'Write footage search queries for "{{ topic }}".\n'
    'Available providers: {{ footage.providers }}\n'
    'Sourcing mode: {{ footage.sourcing_mode }}\n'
    'Scenes: {{ chapter_scenes }}\n'
    'Return one FootageQuery per scene, matching scene_idx values.'
)

_TEMPLATES = [
    ('script_documentary', 'Documentary script', _SCRIPT_SYSTEM, _SCRIPT_USER),
    (
        'scene_breakdown_documentary',
        'Documentary scene breakdown',
        _BREAKDOWN_SYSTEM,
        _BREAKDOWN_USER,
    ),
    ('footage_queries', 'Footage queries', _QUERIES_SYSTEM, _QUERIES_USER),
]

_OVERRIDES = {
    'script': 'script_documentary',
    'scene_breakdown': 'scene_breakdown_documentary',
    'footage_queries': 'footage_queries',
}


class Command(BaseCommand):
    """Seed documentary story formats and prompts (idempotent upsert)."""

    help = 'Seed documentary StoryFormats and their prompt templates'

    @override
    def handle(self, *args: object, **options: object) -> None:
        """Create or update documentary formats and prompt versions."""
        from server.apps.prompts.models import (  # noqa: PLC0415
            PromptScope,
            PromptTemplate,
            PromptVersion,
            StoryFormat,
        )

        for key, name, system, user in _TEMPLATES:
            template, _ = PromptTemplate.objects.update_or_create(
                key=key,
                defaults={'name': name, 'scope': PromptScope.GLOBAL},
            )
            PromptVersion.objects.update_or_create(
                template=template,
                version=1,
                defaults={
                    'system_prompt': system,
                    'user_prompt': user,
                    'is_active': True,
                },
            )
            self.stdout.write(self.style.SUCCESS(f'Seeded prompt: {key}'))

        formats = [
            (
                'documentary_stock',
                'Documentary (stock footage)',
                {'scene_seconds': [6, 12], 'hero_ratio': 0.15},
            ),
            (
                'documentary_archival',
                'Documentary (archival)',
                {'scene_seconds': [8, 14], 'hero_ratio': 0.10},
            ),
        ]
        for key, name, pacing in formats:
            fmt, _ = StoryFormat.objects.update_or_create(
                key=key,
                defaults={
                    'name': name,
                    'fiction': False,
                    'narration_pov': 'narrator',
                    'beats': _DOC_BEATS,
                    'pacing': pacing,
                    'prompt_overrides': dict(_OVERRIDES),
                    'music_mood_map': {
                        'cold_open_hook': 'tense',
                        'escalating_evidence': 'driving',
                        'resolution': 'reflective',
                    },
                    'is_active': True,
                },
            )
            self.stdout.write(
                self.style.SUCCESS(f'Seeded format: {fmt.key}'),
            )
