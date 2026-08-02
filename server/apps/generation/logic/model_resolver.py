"""Per-stage LLM model resolution for PydanticAI agents."""

import logging
from decimal import Decimal

from django.conf import settings

from server.apps.generation.logic.constants import (
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_PROVIDER,
)

logger = logging.getLogger('***REMOVED***.generation.model_resolver')

# Bare model slugs (stored in PromptVersion.model and STAGE_MODEL_DEFAULTS).
STAGE_MODEL_DEFAULTS: dict[str, str] = {
    'research': 'gpt-5.6-terra',
    'outline': 'gpt-5.6-terra',
    'script': 'claude-opus-4-8',
    'scene_breakdown': 'gpt-5.6-terra',
    'narrative_qc': 'claude-opus-4-8',
    'visual_prompts': 'claude-sonnet-4-6',
    'music_plan': 'gpt-5.6-terra',
    'metadata': 'gpt-5.6-terra',
    'editor_brief': 'gpt-5.6-terra',
    'ideation': 'gpt-5.6-terra',
    'clip_analyze': 'claude-sonnet-4-6',
}

# Per-model approximate token costs (USD): (input, output).
MODEL_COSTS: dict[str, tuple[Decimal, Decimal]] = {
    'gpt-5.6-terra': (
        Decimal('0.0000025'),
        Decimal('0.000015'),
    ),
    'claude-opus-4-8': (
        Decimal('0.000015'),
        Decimal('0.000075'),
    ),
    'claude-sonnet-4-6': (
        Decimal('0.000003'),
        Decimal('0.000015'),
    ),
}

_ANTHROPIC_PREFIX = 'claude-'


def _anthropic_api_key_configured() -> bool:
    return bool(getattr(settings, 'ANTHROPIC_API_KEY', ''))


def to_pydantic_ai_model(slug: str) -> str:
    """Map a bare DB slug to a PydanticAI model identifier string."""
    assert slug, 'model slug must be non-empty'  # noqa: S101
    if slug.startswith(_ANTHROPIC_PREFIX):
        return f'anthropic:{slug}'
    return f'openai-responses:{slug}'


def parse_model_slug(slug: str) -> tuple[str, str]:
    """Return (provider, model_name) for cost recording."""
    assert slug, 'model slug must be non-empty'  # noqa: S101
    if slug.startswith(_ANTHROPIC_PREFIX):
        return 'anthropic', slug
    return DEFAULT_LLM_PROVIDER, slug


def resolve_model(stage_key: str, prompt_model: str | None) -> str:
    """Pick the bare model slug for a stage.

    Resolution order: prompt version model, stage default, global default.
    Falls back to OpenAI when Anthropic is requested but no API key is set.
    """
    slug = (
        prompt_model
        or STAGE_MODEL_DEFAULTS.get(stage_key)
        or DEFAULT_LLM_MODEL
    )
    if (
        slug.startswith(_ANTHROPIC_PREFIX)
        and not _anthropic_api_key_configured()
    ):
        logger.warning(
            'ANTHROPIC_API_KEY not set; falling back to %s for stage %s',
            DEFAULT_LLM_MODEL,
            stage_key,
        )
        return DEFAULT_LLM_MODEL
    return slug


def model_token_costs(slug: str) -> tuple[Decimal, Decimal]:
    """Return (input_cost_per_token, output_cost_per_token) for a model slug."""
    costs = MODEL_COSTS.get(slug)
    if costs is not None:
        return costs
    return MODEL_COSTS[DEFAULT_LLM_MODEL]
