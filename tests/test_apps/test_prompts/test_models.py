import pytest

from server.apps.prompts.models import (
    PromptScope,
    PromptTemplate,
    PromptVersion,
    StoryFormat,
)


# Non-DB: enum and default checks
def test_prompt_scope_choices() -> None:
    assert set(PromptScope.values) == {'GLOBAL', 'NICHE', 'CHANNEL'}


def test_prompt_version_default_model() -> None:
    tmpl = PromptTemplate(name='t', key='k', scope=PromptScope.GLOBAL)
    pv = PromptVersion(
        template=tmpl,
        version=1,
        system_prompt='s',
        user_prompt='u',
    )
    assert pv.model == 'gpt-5.2'
    assert pv.temperature == 1.0
    assert pv.max_tokens == 8192
    assert pv.is_active is False


def test_prompt_template_str() -> None:
    tmpl = PromptTemplate(
        name='Scene Breakdown',
        key='scene_breakdown',
        scope=PromptScope.GLOBAL,
    )
    assert str(tmpl) == 'scene_breakdown'


def test_prompt_version_str() -> None:
    tmpl = PromptTemplate(name='t', key='script', scope=PromptScope.GLOBAL)
    pv = PromptVersion(
        template=tmpl,
        version=3,
        system_prompt='s',
        user_prompt='u',
    )
    assert str(pv) == 'script v3'


def test_story_format_defaults() -> None:
    sf = StoryFormat(key='listicle', name='Listicle', beats=[])
    assert sf.fiction is False
    assert sf.narration_pov == 'narrator'
    assert sf.is_active is True
    assert sf.pacing == {}
    assert sf.prompt_overrides == {}
    assert sf.music_mood_map == {}


def test_story_format_str() -> None:
    sf = StoryFormat(key='true_crime', name='True Crime Case', beats=[])
    assert str(sf) == 'True Crime Case'


# DB tests — activated in Task 5 after migrations
@pytest.mark.django_db
def test_prompt_template_key_is_unique() -> None:
    PromptTemplate.objects.create(
        name='Scene Breakdown',
        key='scene_breakdown',
        scope=PromptScope.GLOBAL,
    )
    with pytest.raises(Exception):
        PromptTemplate.objects.create(
            name='Dupe',
            key='scene_breakdown',
            scope=PromptScope.GLOBAL,
        )


@pytest.mark.django_db
def test_prompt_version_unique_constraint() -> None:
    tmpl = PromptTemplate.objects.create(
        name='Script',
        key='script',
        scope=PromptScope.CHANNEL,
    )
    PromptVersion.objects.create(
        template=tmpl,
        version=1,
        system_prompt='sys',
        user_prompt='usr',
    )
    with pytest.raises(Exception):
        PromptVersion.objects.create(
            template=tmpl,
            version=1,
            system_prompt='dup',
            user_prompt='.',
        )


@pytest.mark.django_db
def test_story_format_key_is_unique() -> None:
    StoryFormat.objects.create(
        key='true_crime_case',
        name='True Crime Case',
        beats=[{'key': 'cold_open', 'pct': 0.05}],
    )
    with pytest.raises(Exception):
        StoryFormat.objects.create(key='true_crime_case', name='Dupe', beats=[])
