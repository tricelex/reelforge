"""Tests for seed_script_prompt management command."""

import pytest
from django.core.management import call_command

from server.apps.generation.logic.model_resolver import STAGE_MODEL_DEFAULTS
from server.apps.prompts.logic.script_prompts import (
    SCRIPT_SYSTEM_PROMPT,
    SCRIPT_TEMPLATE_KEY,
    SCRIPT_USER_PROMPT,
)
from server.apps.prompts.models import (
    PromptScope,
    PromptTemplate,
    PromptVersion,
)


@pytest.mark.django_db
def test_seeds_active_script_version() -> None:
    call_command('seed_script_prompt')
    template = PromptTemplate.objects.get(key=SCRIPT_TEMPLATE_KEY)
    active = PromptVersion.objects.filter(template=template, is_active=True)
    assert active.count() == 1
    version = active.get()
    assert version.system_prompt == SCRIPT_SYSTEM_PROMPT
    assert version.user_prompt == SCRIPT_USER_PROMPT
    assert '{{ topic }}' in version.user_prompt
    assert 'eleven_v3' in version.system_prompt
    assert version.model == STAGE_MODEL_DEFAULTS['script']


@pytest.mark.django_db
def test_command_is_idempotent() -> None:
    call_command('seed_script_prompt')
    call_command('seed_script_prompt')
    assert PromptTemplate.objects.filter(key=SCRIPT_TEMPLATE_KEY).count() == 1
    assert (
        PromptVersion.objects.filter(
            template__key=SCRIPT_TEMPLATE_KEY,
            system_prompt=SCRIPT_SYSTEM_PROMPT,
        ).count()
        == 1
    )
    assert (
        PromptVersion.objects.filter(
            template__key=SCRIPT_TEMPLATE_KEY,
            is_active=True,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_creates_new_version_when_old_text_differs() -> None:
    template = PromptTemplate.objects.create(
        key=SCRIPT_TEMPLATE_KEY,
        name='Narration Script',
        scope=PromptScope.GLOBAL,
    )
    PromptVersion.objects.create(
        template=template,
        version=1,
        system_prompt='old system',
        user_prompt='old user',
        is_active=True,
    )
    call_command('seed_script_prompt')
    assert PromptVersion.objects.filter(template=template).count() == 2
    active = PromptVersion.objects.get(template=template, is_active=True)
    assert active.version == 2
    assert active.system_prompt == SCRIPT_SYSTEM_PROMPT
    old = PromptVersion.objects.get(template=template, version=1)
    assert old.is_active is False
