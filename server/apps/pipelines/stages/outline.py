"""Outline stage — chapter structure generation."""

from functools import cache
from typing import Any, override

from pydantic_ai import Agent, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.pipelines.schemas import OutlineOutput
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@cache
def _agent() -> Agent[StageContext, OutlineOutput]:
    """Create and cache the outline agent on first call."""
    a: Agent[StageContext, OutlineOutput] = Agent(
        'anthropic:claude-opus-4-8',
        output_type=OutlineOutput,
        deps_type=StageContext,
    )

    @a.system_prompt
    async def _sys(ctx: RunContext[StageContext]) -> str:  # pragma: no cover
        sys, _ = await ctx.deps.prompts.render(
            'outline',
            {'topic': ctx.deps.run.topic},
        )
        return sys or (
            'You are a documentary outline writer. '
            'Produce a chapter structure with 6-10 chapters. '
            'Each chapter needs a retention device (open_loop, payoff, '
            'pattern_interrupt, tension_build, closure, engagement_cta).'
        )

    return a


@register_stage
class OutlineStage(Stage):
    """Stage 2: documentary chapter outline."""

    key = 'outline'
    queue = 'api'
    max_retries = 3
    timeout_s = 120

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Generate a structured chapter outline from the research brief."""
        research = ctx.upstream.get('research', {})
        brief = research.get('brief', {})
        niche = getattr(ctx.channel, 'niche_config', None)
        beats: list[dict[str, Any]] = []
        if niche and getattr(niche, 'format', None):
            beats = getattr(niche.format, 'beats', [])
        total_s = ctx.config.get('total_target_seconds', 1320)

        _, usr = await ctx.prompts.render(
            'outline',
            {
                'topic': ctx.run.topic,
                'research_brief': brief,
                'beats': beats,
                'total_target_seconds': total_s,
            },
        )
        user_prompt = usr or (
            f'Topic: {ctx.run.topic}\n'
            f'Research brief: {brief}\n'
            f'Format beats: {beats}\n'
            f'Target total duration: {total_s}s (~{total_s // 60} min).\n'
            f'Write a chapter outline with 6-10 chapters.'
        )
        output: OutlineOutput = await llm_client.run_agent(
            _agent(),
            user_prompt,
            ctx,
            stage_key=self.key,
        )
        return output.model_dump()
