"""Tests for PromptRenderer — versioned Jinja2 template rendering."""

import asyncio
from typing import Any

import pytest

from server.apps.pipelines.services.prompt_renderer import PromptRenderer
from server.apps.prompts.models import (
    PromptScope,
    PromptTemplate,
    PromptVersion,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.mark.django_db(transaction=True)
def test_render_system_ignores_variables_only_the_user_prompt_needs() -> None:
    """system_prompt hooks call render_system() with a base variable set.

    The user_prompt may reference per-item extras (e.g. the chapter being
    processed) that aren't available yet when the system prompt is built.
    render_system() must not choke on those — only render() needs them.
    """
    template = PromptTemplate.objects.create(
        name='Scene Breakdown',
        key='scene_breakdown_test',
        scope=PromptScope.GLOBAL,
    )
    PromptVersion.objects.create(
        template=template,
        version=1,
        system_prompt='You are a scene breakdown specialist for {{ topic }}.',
        user_prompt='Break chapter {{ chapter.idx }}: {{ chapter.text }}',
        is_active=True,
    )
    renderer = PromptRenderer({})

    sys = _run(
        renderer.render_system(
            'scene_breakdown_test',
            {'topic': 'The fall of Rome'},
        ),
    )

    assert sys == 'You are a scene breakdown specialist for The fall of Rome.'


@pytest.mark.django_db(transaction=True)
def test_render_still_requires_full_variables_for_both_halves() -> None:
    """render() renders both templates and still needs the full variable set."""
    template = PromptTemplate.objects.create(
        name='Scene Breakdown',
        key='scene_breakdown_test2',
        scope=PromptScope.GLOBAL,
    )
    PromptVersion.objects.create(
        template=template,
        version=1,
        system_prompt='sys for {{ topic }}',
        user_prompt='Break chapter {{ chapter.idx }}',
        is_active=True,
    )
    renderer = PromptRenderer({})

    sys, usr = _run(
        renderer.render(
            'scene_breakdown_test2',
            {'topic': 'Rome', 'chapter': {'idx': 1}},
        ),
    )

    assert sys == 'sys for Rome'
    assert usr == 'Break chapter 1'
