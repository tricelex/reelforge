"""Tests for the documentary format and prompt seeding command."""

import pytest
from django.core.management import call_command

from server.apps.prompts.models import (
    PromptTemplate,
    PromptVersion,
    StoryFormat,
)


@pytest.mark.django_db
def test_seeds_both_documentary_formats() -> None:
    """Both formats exist with documentary beats and no fiction flag."""
    call_command('seed_story_formats')
    keys = set(StoryFormat.objects.values_list('key', flat=True))
    assert {'documentary_stock', 'documentary_archival'} <= keys
    fmt = StoryFormat.objects.get(key='documentary_stock')
    assert fmt.fiction is False
    assert fmt.narration_pov == 'narrator'
    assert len(fmt.beats) >= 5


@pytest.mark.django_db
def test_formats_point_at_documentary_prompt_templates() -> None:
    """prompt_overrides map stage keys to documentary template keys."""
    call_command('seed_story_formats')
    fmt = StoryFormat.objects.get(key='documentary_stock')
    assert fmt.prompt_overrides['script'] == 'script_documentary'
    assert (
        fmt.prompt_overrides['scene_breakdown'] == 'scene_breakdown_documentary'
    )


@pytest.mark.django_db
def test_seeds_active_prompt_versions() -> None:
    """Each new template has exactly one active version."""
    call_command('seed_story_formats')
    for key in (
        'script_documentary',
        'scene_breakdown_documentary',
        'footage_queries',
    ):
        template = PromptTemplate.objects.get(key=key)
        active = PromptVersion.objects.filter(
            template=template,
            is_active=True,
        )
        assert active.count() == 1
        assert active.first().system_prompt


@pytest.mark.django_db
def test_command_is_idempotent() -> None:
    """Running twice creates no duplicates."""
    call_command('seed_story_formats')
    call_command('seed_story_formats')
    assert StoryFormat.objects.filter(key='documentary_stock').count() == 1
    assert PromptTemplate.objects.filter(key='script_documentary').count() == 1
    assert (
        PromptVersion.objects.filter(
            template__key='script_documentary',
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_archival_format_prefers_stills() -> None:
    """The archival format's overrides differ from the stock format's."""
    call_command('seed_story_formats')
    archival = StoryFormat.objects.get(key='documentary_archival')
    assert archival.prompt_overrides['script'] == 'script_documentary'
    assert archival.pacing


@pytest.mark.django_db
def test_documentary_breakdown_prompt_requires_verbatim_slices() -> None:
    """Documentary scenes stay on-script; they do not invent narration."""
    call_command('seed_story_formats')
    template = PromptTemplate.objects.get(key='scene_breakdown_documentary')
    active = PromptVersion.objects.get(template=template, is_active=True)
    assert 'contiguous verbatim slice' in active.system_prompt
    assert 'Keep setting stable' in active.system_prompt
    assert 'empty cast' in active.system_prompt.lower()
