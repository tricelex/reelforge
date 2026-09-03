"""Tests for per-stage LLM model resolution."""

import pytest
from django.test import override_settings

from server.apps.generation.logic.constants import DEFAULT_LLM_MODEL
from server.apps.generation.logic.model_resolver import (
    STAGE_MODEL_DEFAULTS,
    model_token_costs,
    parse_model_slug,
    resolve_model,
    to_pydantic_ai_model,
)


def test_to_pydantic_ai_model_openai() -> None:
    assert to_pydantic_ai_model('gpt-5.6-terra') == (
        'openai-responses:gpt-5.6-terra'
    )


def test_to_pydantic_ai_model_anthropic() -> None:
    assert to_pydantic_ai_model('claude-opus-4-8') == (
        'anthropic:claude-opus-4-8'
    )


def test_parse_model_slug_openai() -> None:
    assert parse_model_slug('gpt-5.6-terra') == ('openai', 'gpt-5.6-terra')


def test_parse_model_slug_anthropic() -> None:
    assert parse_model_slug('claude-sonnet-4-6') == (
        'anthropic',
        'claude-sonnet-4-6',
    )


def test_resolve_model_prefers_prompt_version() -> None:
    assert resolve_model('script', 'gpt-5.6-terra') == 'gpt-5.6-terra'


def test_resolve_model_uses_stage_default() -> None:
    with override_settings(ANTHROPIC_API_KEY='sk-ant-test'):
        assert resolve_model('script', None) == STAGE_MODEL_DEFAULTS['script']


def test_channel_research_stage_default_is_sonnet() -> None:
    """Sonnet, not Opus - a multi-turn stage feels the per-token gap most."""
    assert STAGE_MODEL_DEFAULTS['channel_research'] == 'claude-sonnet-4-6'


def test_resolve_model_global_fallback() -> None:
    assert resolve_model('unknown_stage', None) == DEFAULT_LLM_MODEL


@override_settings(ANTHROPIC_API_KEY='')
def test_resolve_model_falls_back_without_anthropic_key() -> None:
    assert resolve_model('script', 'claude-opus-4-8') == DEFAULT_LLM_MODEL


@override_settings(ANTHROPIC_API_KEY='sk-ant-test')
def test_resolve_model_uses_anthropic_when_key_set() -> None:
    assert resolve_model('script', 'claude-opus-4-8') == 'claude-opus-4-8'


def test_model_token_costs_known_model() -> None:
    input_cost, output_cost = model_token_costs('claude-opus-4-8')
    assert input_cost > 0
    assert output_cost > 0


def test_model_token_costs_unknown_model_falls_back() -> None:
    fallback = model_token_costs(DEFAULT_LLM_MODEL)
    assert model_token_costs('unknown-model') == fallback


@pytest.mark.django_db
def test_prompt_renderer_get_model_returns_version_model() -> None:
    """get_model() reads PromptVersion.model from the active version."""
    from asgiref.sync import async_to_sync

    from server.apps.pipelines.services.prompt_renderer import PromptRenderer
    from server.apps.prompts.models import PromptTemplate, PromptVersion

    template = PromptTemplate.objects.create(
        key='test_model_renderer',
        name='Test',
        scope='GLOBAL',
    )
    PromptVersion.objects.create(
        template=template,
        version=1,
        system_prompt='sys',
        user_prompt='usr',
        model='claude-sonnet-4-6',
        is_active=True,
    )
    renderer = PromptRenderer({})
    model = async_to_sync(renderer.get_model)('test_model_renderer')
    assert model == 'claude-sonnet-4-6'
