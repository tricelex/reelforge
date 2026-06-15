"""PydanticAI agent runner — records token costs and returns typed output."""

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

if TYPE_CHECKING:
    from server.apps.pipelines.stages.base import StageContext

# Per-token costs for claude-opus-4-8.
_INPUT_COST_PER_TOKEN = Decimal('0.000015')
_OUTPUT_COST_PER_TOKEN = Decimal('0.000075')


async def run_agent(
    agent: 'Agent[Any, Any]',
    user_prompt: str,
    ctx: 'StageContext',
    stage_key: str,
    request_limit: int = 4,
) -> Any:
    """Run a PydanticAI agent, record token costs, and return typed output."""
    result = await agent.run(
        user_prompt,
        deps=ctx,
        usage_limits=UsageLimits(request_limit=request_limit),
    )
    usage = result.usage
    if usage.input_tokens:
        await ctx.costs.record(
            provider='anthropic',
            operation=f'claude-opus-4-8/{stage_key}/input',
            units=usage.input_tokens,
            unit_cost_usd=_INPUT_COST_PER_TOKEN,
        )
    if usage.output_tokens:
        await ctx.costs.record(
            provider='anthropic',
            operation=f'claude-opus-4-8/{stage_key}/output',
            units=usage.output_tokens,
            unit_cost_usd=_OUTPUT_COST_PER_TOKEN,
        )
    return result.output
