"""PydanticAI agent runner — records token costs and returns typed output."""

import inspect
from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from server.apps.generation.logic.constants import DEFAULT_LLM_MODEL
from server.apps.generation.logic.model_resolver import (
    model_token_costs,
    parse_model_slug,
)
from server.common.exceptions import RetryableProviderError

if TYPE_CHECKING:
    from server.apps.pipelines.stages.base import StageContext

# Anthropic's pydantic-ai default is 4096 — too small for multi-chapter
# structured outputs (script, scene_breakdown). Match PromptVersion default.
_DEFAULT_MAX_TOKENS = 8192


async def _load_prompt_settings(
    ctx: 'StageContext',
    stage_key: str,
) -> dict[str, Any]:
    """Return PromptRenderer generation settings, or {} if unavailable."""
    get_settings = getattr(
        getattr(ctx, 'prompts', None),
        'get_generation_settings',
        None,
    )
    if not callable(get_settings):
        return {}
    raw = get_settings(stage_key)
    settings = await raw if inspect.isawaitable(raw) else raw
    return settings if isinstance(settings, dict) else {}


def _coerce_max_tokens(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    return None


def _coerce_temperature(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


async def _resolve_generation_settings(
    ctx: 'StageContext',
    stage_key: str,
    *,
    max_tokens: int | None,
    temperature: float | None,
) -> ModelSettings:
    """Build ModelSettings from overrides or the stage PromptVersion."""
    prompt_settings = await _load_prompt_settings(ctx, stage_key)
    resolved_max = max_tokens or _coerce_max_tokens(
        prompt_settings.get('max_tokens'),
    )
    resolved_temp = (
        temperature
        if temperature is not None
        else _coerce_temperature(prompt_settings.get('temperature'))
    )
    model_settings: ModelSettings = {
        'max_tokens': resolved_max or _DEFAULT_MAX_TOKENS,
    }
    if resolved_temp is not None:
        model_settings['temperature'] = resolved_temp
    return model_settings


async def run_agent(
    agent: 'Agent[Any, Any]',
    user_prompt: str,
    ctx: 'StageContext',
    stage_key: str,
    request_limit: int = 4,
    *,
    model_slug: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    input_tokens_limit: int | None = None,
    count_tokens_before_request: bool = False,
) -> Any:
    """Run a PydanticAI agent, record token costs, and return typed output."""
    slug = model_slug or DEFAULT_LLM_MODEL
    provider, model_name = parse_model_slug(slug)
    input_cost, output_cost = model_token_costs(slug)
    model_settings = await _resolve_generation_settings(
        ctx,
        stage_key,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    try:
        result = await agent.run(
            user_prompt,
            deps=ctx,
            model_settings=model_settings,
            usage_limits=UsageLimits(
                request_limit=request_limit,
                input_tokens_limit=input_tokens_limit,
                count_tokens_before_request=count_tokens_before_request,
            ),
        )
    except UnexpectedModelBehavior as exc:
        # Structured-output / validator failures after pydantic-ai's internal
        # retries — treat as stage-retryable so ScriptStage.max_retries applies.
        detail = str(exc)
        cause = exc.__cause__
        if cause is not None:
            detail = f'{detail}: {cause}'
        raise RetryableProviderError(
            detail,
            provider=provider,
        ) from exc
    usage = result.usage
    if usage.input_tokens:
        await ctx.costs.record(
            provider=provider,
            operation=f'{model_name}/{stage_key}/input',
            units=usage.input_tokens,
            unit_cost_usd=input_cost,
        )
    if usage.output_tokens:
        await ctx.costs.record(
            provider=provider,
            operation=f'{model_name}/{stage_key}/output',
            units=usage.output_tokens,
            unit_cost_usd=output_cost,
        )
    return result.output
