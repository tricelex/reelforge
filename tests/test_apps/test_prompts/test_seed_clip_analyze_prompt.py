"""Tests for seed_clip_analyze_prompt management command."""

import pytest
from django.core.management import call_command

from server.apps.prompts.logic.clip_analyze_prompts import (
    CLIP_ANALYZE_SYSTEM_PROMPT,
    CLIP_ANALYZE_TEMPLATE_KEY,
    CLIP_ANALYZE_USER_PROMPT,
)
from server.apps.prompts.models import (
    PromptScope,
    PromptTemplate,
    PromptVersion,
)


@pytest.mark.django_db
def test_seeds_active_viral_clip_analyze_version() -> None:
    call_command('seed_clip_analyze_prompt')
    template = PromptTemplate.objects.get(key=CLIP_ANALYZE_TEMPLATE_KEY)
    active = PromptVersion.objects.filter(template=template, is_active=True)
    assert active.count() == 1
    version = active.get()
    assert version.system_prompt == CLIP_ANALYZE_SYSTEM_PROMPT
    assert version.user_prompt == CLIP_ANALYZE_USER_PROMPT
    assert 'hook_score' in version.user_prompt
    assert 'relevance_score' not in version.user_prompt


@pytest.mark.django_db
def test_command_is_idempotent() -> None:
    call_command('seed_clip_analyze_prompt')
    call_command('seed_clip_analyze_prompt')
    assert PromptTemplate.objects.filter(
        key=CLIP_ANALYZE_TEMPLATE_KEY,
    ).count() == 1
    assert PromptVersion.objects.filter(
        template__key=CLIP_ANALYZE_TEMPLATE_KEY,
        system_prompt=CLIP_ANALYZE_SYSTEM_PROMPT,
    ).count() == 1
    assert PromptVersion.objects.filter(
        template__key=CLIP_ANALYZE_TEMPLATE_KEY,
        is_active=True,
    ).count() == 1


@pytest.mark.django_db
def test_creates_new_version_when_old_text_differs() -> None:
    template = PromptTemplate.objects.create(
        key=CLIP_ANALYZE_TEMPLATE_KEY,
        name='Clip Analysis',
        scope=PromptScope.GLOBAL,
    )
    PromptVersion.objects.create(
        template=template,
        version=1,
        system_prompt='old system',
        user_prompt='old user',
        is_active=True,
    )
    call_command('seed_clip_analyze_prompt')
    assert PromptVersion.objects.filter(template=template).count() == 2
    active = PromptVersion.objects.get(template=template, is_active=True)
    assert active.version == 2
    assert active.system_prompt == CLIP_ANALYZE_SYSTEM_PROMPT
    old = PromptVersion.objects.get(template=template, version=1)
    assert old.is_active is False
