"""Tests for format-driven prompt selection and the footage namespace."""

import pytest

from server.apps.channels.models import (
    Channel,
    ChannelKind,
    NicheConfig,
)
from server.apps.pipelines.services.pipeline_run import (
    build_prompt_overrides_snapshot,
)
from server.apps.pipelines.services.prompt_renderer import PromptRenderer
from server.apps.prompts.models import (
    PromptScope,
    PromptTemplate,
    PromptVersion,
    StoryFormat,
)


@pytest.fixture
def channel(db: None) -> Channel:
    return Channel.objects.create(name='Doc', kind=ChannelKind.LONGFORM)


@pytest.mark.django_db
def test_channel_without_format_gets_empty_snapshot(
    channel: Channel,
) -> None:
    """Existing longform channels are completely unaffected."""
    assert build_prompt_overrides_snapshot(channel) == {}


@pytest.mark.django_db
def test_format_with_no_overrides_gets_empty_snapshot(
    channel: Channel,
) -> None:
    """A format with the default empty overrides changes nothing."""
    fmt = StoryFormat.objects.create(
        key='plain',
        name='Plain',
        beats=[],
        prompt_overrides={},
    )
    NicheConfig.objects.create(channel=channel, format=fmt)
    channel.refresh_from_db()
    assert build_prompt_overrides_snapshot(channel) == {}


@pytest.mark.django_db
def test_overrides_resolve_to_active_prompt_version(
    channel: Channel,
) -> None:
    """A template key maps to the currently-active version id."""
    template = PromptTemplate.objects.create(
        name='Doc script',
        key='script_documentary',
        scope=PromptScope.GLOBAL,
    )
    active = PromptVersion.objects.create(
        template=template,
        version=2,
        system_prompt='s',
        user_prompt='u',
        is_active=True,
    )
    PromptVersion.objects.create(
        template=template,
        version=1,
        system_prompt='old',
        user_prompt='old',
        is_active=False,
    )
    fmt = StoryFormat.objects.create(
        key='doc',
        name='Doc',
        beats=[],
        prompt_overrides={'script': 'script_documentary'},
    )
    NicheConfig.objects.create(channel=channel, format=fmt)
    channel.refresh_from_db()

    snapshot = build_prompt_overrides_snapshot(channel)
    assert snapshot == {'script': str(active.id)}


@pytest.mark.django_db
def test_override_naming_a_missing_template_is_skipped(
    channel: Channel,
) -> None:
    """A typo'd template key degrades to the global default, not a crash."""
    fmt = StoryFormat.objects.create(
        key='doc',
        name='Doc',
        beats=[],
        prompt_overrides={'script': 'no_such_template'},
    )
    NicheConfig.objects.create(channel=channel, format=fmt)
    channel.refresh_from_db()
    assert build_prompt_overrides_snapshot(channel) == {}


@pytest.mark.anyio
@pytest.mark.django_db
async def test_renderer_reads_nested_prompts_key() -> None:
    """Resolved prompts live under snapshot['prompts']."""
    template = await PromptTemplate.objects.acreate(
        name='T',
        key='script',
        scope=PromptScope.GLOBAL,
    )
    version = await PromptVersion.objects.acreate(
        template=template,
        version=1,
        system_prompt='sys {{ topic }}',
        user_prompt='usr',
        is_active=True,
    )
    renderer = PromptRenderer({'prompts': {'script': str(version.id)}})
    sys, _ = await renderer.render('script', {'topic': 'Rome'})
    assert sys == 'sys Rome'


@pytest.mark.anyio
@pytest.mark.django_db
async def test_renderer_still_reads_flat_keys() -> None:
    """The pre-nesting flat layout keeps working."""
    template = await PromptTemplate.objects.acreate(
        name='T',
        key='outline',
        scope=PromptScope.GLOBAL,
    )
    version = await PromptVersion.objects.acreate(
        template=template,
        version=1,
        system_prompt='flat',
        user_prompt='u',
        is_active=True,
    )
    renderer = PromptRenderer({'outline': str(version.id)})
    sys, _ = await renderer.render('outline', {})
    assert sys == 'flat'


@pytest.mark.django_db
def test_clip_metadata_keys_do_not_leak_into_prompt_lookup() -> None:
    """Clipping metadata in the snapshot is not mistaken for a version id."""
    renderer = PromptRenderer({
        'source_title': 'A video',
        'clip_options': {'auto_approve': True},
    })
    assert renderer._snapshot.get('prompts') is None
