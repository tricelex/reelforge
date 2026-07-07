"""Outline stage — chapter structure generation."""

import random
from functools import cache
from typing import Any, override

from pydantic_ai import Agent, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.generation.logic.constants import PYDANTIC_AI_MODEL
from server.apps.pipelines.schemas import OutlineOutput
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


def _pick_format(
    pool: list[Any],
    recent_keys: set[str],
) -> tuple[list[dict[str, Any]], str]:
    """Weighted-random pick from pool, avoiding recently-used keys."""
    if not pool:
        return [], ''
    candidates = [f for f in pool if f.key not in recent_keys] or list(pool)
    chosen = random.choice(candidates)  # noqa: S311
    return chosen.beats, chosen.key


async def _recent_format_keys(
    channel_id: str,
    exclude_run_id: str,
    limit: int = 2,
) -> set[str]:
    """format_key values from the channel's recent SUCCEEDED outline runs."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    keys: set[str] = set()
    async for exec_ in (
        StageExecution.objects
        .filter(
            run__channel_id=channel_id,
            stage_key='outline',
            status=StageStatus.SUCCEEDED,
        )
        .exclude(run__id=exclude_run_id)
        .order_by('-finished_at')[:limit]
    ):
        key = exec_.output.get('format_key', '')
        if key:
            keys.add(key)
    return keys


@cache
def _agent() -> Agent[StageContext, OutlineOutput]:
    """Create and cache the outline agent on first call."""
    a: Agent[StageContext, OutlineOutput] = Agent(
        PYDANTIC_AI_MODEL,
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
        format_key = ''
        if niche:
            pool = list(niche.format_pool.filter(is_active=True))
            if len(pool) > 1:
                recent_keys = await _recent_format_keys(
                    str(ctx.channel.id),
                    str(ctx.run.id),
                )
                beats, format_key = _pick_format(pool, recent_keys)
            elif pool:
                beats, format_key = pool[0].beats, pool[0].key
            elif getattr(niche, 'format', None):
                beats = getattr(niche.format, 'beats', [])
                format_key = getattr(niche.format, 'key', '')
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
        result = output.model_dump()
        result['format_key'] = format_key
        return result
