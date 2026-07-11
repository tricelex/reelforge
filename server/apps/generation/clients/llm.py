"""PydanticAI agent runner — records token costs and returns typed output."""

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from server.apps.generation.logic.constants import (
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_PROVIDER,
)

if TYPE_CHECKING:
    from server.apps.pipelines.stages.base import StageContext

# Approximate per-token costs for gpt-5.6-terra (USD).
_INPUT_COST_PER_TOKEN = Decimal('0.0000025')
_OUTPUT_COST_PER_TOKEN = Decimal('0.000015')


async def run_agent(
    agent: 'Agent[Any, Any]',
    user_prompt: str,
    ctx: 'StageContext',
    stage_key: str,
    request_limit: int = 4,
    *,
    input_tokens_limit: int | None = None,
    count_tokens_before_request: bool = False,
) -> Any:
    """Run a PydanticAI agent, record token costs, and return typed output."""
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
            provider=DEFAULT_LLM_PROVIDER,
            operation=f'{DEFAULT_LLM_MODEL}/{stage_key}/input',
            units=usage.input_tokens,
            unit_cost_usd=_INPUT_COST_PER_TOKEN,
        )
    if usage.output_tokens:
        await ctx.costs.record(
            provider=DEFAULT_LLM_PROVIDER,
            operation=f'{DEFAULT_LLM_MODEL}/{stage_key}/output',
            units=usage.output_tokens,
            unit_cost_usd=_OUTPUT_COST_PER_TOKEN,
        )
    return result.output
