"""Pipeline constants exposed to API clients."""

from typing import Final

BLUEPRINT_BY_KIND: Final = {
    'LONGFORM': 'longform_v1',
    'CLIPPING': 'clipping_v1',
    'SHORTS': 'longform_v1',
}

GATE_CATALOG: Final = (
    (
        'script_gate',
        'Script review',
        'Pause after script generation for editorial review.',
    ),
    (
        'storyboard_gate',
        'Storyboard review',
        'Pause after storyboard images before motion and TTS spend.',
    ),
    (
        'character_gate',
        'Character design',
        'Pause for in-run character design approval.',
    ),
    (
        'final_gate',
        'Final review',
        'Pause before publish for final QA.',
    ),
    (
        'clip_approval_gate',
        'Clip approval',
        'Pause clipping runs before rendering approved clips.',
    ),
    (
        'review_gate',
        'Review',
        'Generic review gate used by the publish flow.',
    ),
)
