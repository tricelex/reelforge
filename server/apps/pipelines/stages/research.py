"""Research stage — web search + LLM synthesis."""

from functools import cache
from typing import Any, override

from django.conf import settings
from pydantic_ai import Agent, ModelRetry, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.generation.clients import search as search_client
from server.apps.generation.logic.constants import PYDANTIC_AI_MODEL
from server.apps.pipelines.schemas import ResearchOutput
from server.apps.pipelines.services.prompt_variables import (
    build_prompt_variables,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@cache
def _agent() -> Agent[StageContext, ResearchOutput]:
    """Create and cache the research agent on first call."""
    a: Agent[StageContext, ResearchOutput] = Agent(
        PYDANTIC_AI_MODEL,
        output_type=ResearchOutput,
        deps_type=StageContext,
    )

    @a.system_prompt
    async def _sys(ctx: RunContext[StageContext]) -> str:  # pragma: no cover
        variables = await build_prompt_variables(ctx.deps, include_character=False)
        sys, _ = await ctx.deps.prompts.render('research', variables)
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
        """Search the web for relevant sources.

        Use 2-4 targeted queries total; avoid repeating similar searches.
        """
        api_key: str = getattr(settings, 'EXA_API_KEY', '')
        return await search_client.search(
            query,
            api_key=api_key,
            num_results=search_client.AGENT_NUM_RESULTS,
            content_mode='highlights',
            max_characters_per_result=search_client.AGENT_MAX_CHARACTERS_PER_RESULT,
            max_total_characters=search_client.AGENT_MAX_TOTAL_CHARACTERS,
        )

    @a.output_validator
    def _validate(  # pragma: no cover
        ctx: RunContext[StageContext],
        output: ResearchOutput,
    ) -> ResearchOutput:
        """Reject briefs with mostly single-sourced key facts."""
        try:
            output.brief.model_validate(output.brief.model_dump())
        except ValueError as exc:
            raise ModelRetry(str(exc)) from exc
        return output

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
        variables = await build_prompt_variables(
            ctx,
            include_character=False,
        )
        _, usr = await ctx.prompts.render('research', variables)
        user_prompt = usr or (
            f'Research "{ctx.run.topic}". '
            f'Target audience: {audience or "general"}. '
            f'Angle: {angle or "factual overview"}. '
            f'Find 6-10 key facts with sources, identify 3-5 narrative angles, '
            f'and surface 2-3 surprising hooks. '
            f'For each key fact in the brief, at least 2 of your sources must '
            f'independently state it (put the matching wording in that '
            f"source's own key_facts list) — prefer primary/archival/academic "
            f'sources when available.'
        )
        output: ResearchOutput = await llm_client.run_agent(
            _agent(),
            user_prompt,
            ctx,
            stage_key=self.key,
            request_limit=5,
            input_tokens_limit=200_000,
            count_tokens_before_request=True,
        )
        return output.model_dump()
