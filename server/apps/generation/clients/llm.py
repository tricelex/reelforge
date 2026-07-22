"""PydanticAI agent runner — records token costs and returns typed output."""

from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from server.apps.generation.logic.constants import DEFAULT_LLM_MODEL
from server.apps.generation.logic.model_resolver import (
    model_token_costs,
    parse_model_slug,
)

if TYPE_CHECKING:
    from server.apps.pipelines.stages.base import StageContext


async def run_agent(
    agent: 'Agent[Any, Any]',
    user_prompt: str,
    ctx: 'StageContext',
    stage_key: str,
    request_limit: int = 4,
    *,
    model_slug: str | None = None,
    input_tokens_limit: int | None = None,
    count_tokens_before_request: bool = False,
) -> Any:
    """Run a PydanticAI agent, record token costs, and return typed output."""
    slug = model_slug or DEFAULT_LLM_MODEL
    provider, model_name = parse_model_slug(slug)
    input_cost, output_cost = model_token_costs(slug)
    result = await agent.run(
        user_prompt,
        deps=ctx,
        usage_limits=UsageLimits(
            request_limit=request_limit,
            input_tokens_limit=input_tokens_limit,
            count_tokens_before_request=count_tokens_before_request,
        ),
    )
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
