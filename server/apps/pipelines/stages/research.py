"""Research stage — web search + LLM synthesis."""

from functools import cache
from typing import Any, override

from django.conf import settings
from pydantic_ai import Agent, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.generation.clients import search as search_client
from server.apps.pipelines.schemas import ResearchOutput
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@cache
def _agent() -> Agent[StageContext, ResearchOutput]:
    """Create and cache the research agent on first call."""
    a: Agent[StageContext, ResearchOutput] = Agent(
        'anthropic:claude-opus-4-8',
        output_type=ResearchOutput,
        deps_type=StageContext,
    )

    @a.system_prompt
    async def _sys(ctx: RunContext[StageContext]) -> str:  # pragma: no cover
        sys, _ = await ctx.deps.prompts.render(
            'research',
            {'topic': ctx.deps.run.topic},
        )
        return sys or (
            'You are a factual research assistant. '
            'Produce a structured research brief with key facts, sources, '
            'narrative angles, and memorable hooks.'
        )

    @a.tool
    async def web_search(
        ctx: RunContext[StageContext],
        query: str,
    ) -> list[dict[str, Any]]:  # pragma: no cover
        """Search the web for relevant sources."""
        api_key: str = getattr(settings, 'EXA_API_KEY', '')
        return await search_client.search(query, api_key=api_key)

    return a


@register_stage
class ResearchStage(Stage):
    """Stage 1: web research synthesis."""

    key = 'research'
    queue = 'api'
    max_retries = 3
    timeout_s = 180

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Search the web and synthesise a research brief."""
        niche = getattr(ctx.channel, 'niche_config', None)
        audience = getattr(niche, 'audience', '') if niche else ''
        angle = getattr(niche, 'angle', '') if niche else ''
        _, usr = await ctx.prompts.render(
            'research',
            {
                'topic': ctx.run.topic,
                'audience': audience,
                'angle': angle,
            },
        )
        user_prompt = usr or (
            f'Research "{ctx.run.topic}". '
            f'Target audience: {audience or "general"}. '
            f'Angle: {angle or "factual overview"}. '
            f'Find 6-10 key facts with sources, identify 3-5 narrative angles, '
            f'and surface 2-3 surprising hooks.'
        )
        output: ResearchOutput = await llm_client.run_agent(
            _agent(),
            user_prompt,
            ctx,
            stage_key=self.key,
            request_limit=8,
        )
        return output.model_dump()
