"""Jinja namespace for pipeline prompt templates."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from server.apps.channels.models import (
    Channel,
    ChannelKind,
    Character,
    CharacterOrigin,
    CharacterStatus,
    NicheConfig,
)
from server.apps.pipelines.services.prompt_renderer import PromptRenderer
from server.apps.pipelines.services.prompt_variables import (
    build_prompt_variables,
)
from server.apps.prompts.models import StoryFormat


def _ctx(*, channel: object, topic: str = 'Ice Age fire') -> MagicMock:
    ctx = MagicMock()
    ctx.run.topic = topic
    ctx.run.id = str(uuid4())
    ctx.channel = channel
    ctx.upstream = {'outline': {'chapters': []}}
    ctx.config = {'total_target_seconds': 780}
    return ctx


def test_format_pacing_and_channel_wpm_render_in_jinja() -> None:
    """Script templates can read format.pacing[beat] and channel.wpm."""
    fmt = SimpleNamespace(
        name='Survival',
        key='survival_scenario',
        fiction=False,
        narration_pov='narrator',
        beats=[
            {'name': 'cold_open_scene', 'description': 'Open on the night.'},
            {'name': 'reflection', 'description': 'Close the loop.'},
        ],
        pacing={'cold_open_scene': 45, 'reflection': 30},
        music_mood_map={'cold_open_scene': 'tense'},
    )
    channel = SimpleNamespace(
        name='Wild Origins',
        kind='LONGFORM',
        wpm=150,
        branding=None,
        niche_config=SimpleNamespace(
            audience='curious viewers',
            angle='survival reframe',
            banned_topics=['ancient aliens'],
            lore_document='Be specific.',
            format=fmt,
        ),
        footage_sourcing=None,
    )
    user_template = (
        'WPM {{ channel.wpm }} / {{ wpm }}\n'
        '{% for beat in format.beats %}'
        '- {{ beat.name }} ({{ format.pacing[beat.name] }}s / '
        '{{ beat.pacing_seconds }}s): {{ beat.description }}\n'
        '{% endfor %}'
    )

    async def _inner() -> None:
        variables = await build_prompt_variables(
            _ctx(channel=channel),
            include_character=False,
        )
        renderer = PromptRenderer({})
        mock_pv = MagicMock()
        mock_pv.system_prompt = ''
        mock_pv.user_prompt = user_template
        with patch('server.apps.prompts.models.PromptVersion') as mock_cls:
            mock_cls.objects.filter.return_value.afirst = AsyncMock(
                return_value=mock_pv,
            )
            _, usr = await renderer.render('script', variables)
        assert 'WPM 150 / 150' in usr
        assert '- cold_open_scene (45s / 45s): Open on the night.' in usr
        assert '- reflection (30s / 30s): Close the loop.' in usr

    asyncio.run(_inner())


@pytest.mark.django_db
@pytest.mark.anyio
@pytest.mark.timeout(30)
async def test_character_persona_falls_back_to_channel_library() -> None:
    """When the run has no cast yet, use an approved channel character."""
    channel = await Channel.objects.acreate(
        name='Hosted',
        kind=ChannelKind.LONGFORM,
        wpm=140,
    )
    await Character.objects.acreate(
        channel=channel,
        name='Ava',
        appearance_prompt='ochre cloak',
        persona='calm guide',
        status=CharacterStatus.APPROVED,
        origin=CharacterOrigin.LIBRARY,
    )
    fmt = await StoryFormat.objects.acreate(
        key='hosted_doc',
        name='Hosted',
        beats=[{'name': 'hook', 'description': 'Start'}],
        pacing={'hook': 20},
        music_mood_map={},
    )
    await NicheConfig.objects.acreate(channel=channel, format=fmt)
    channel = await Channel.objects.select_related(
        'niche_config__format',
        'branding',
        'footage_sourcing',
    ).aget(pk=channel.pk)
    ctx = _ctx(channel=channel)
    variables = await build_prompt_variables(ctx)
    assert variables['character'] is not None
    assert variables['character']['name'] == 'Ava'
    assert variables['character']['persona'] == 'calm guide'
    assert variables['character']['appearance_prompt'] == 'ochre cloak'
