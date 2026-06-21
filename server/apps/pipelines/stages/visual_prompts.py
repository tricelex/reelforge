"""Visual prompts stage — generates Flux image prompts per scene."""

from functools import cache
from typing import Any, override

from pydantic_ai import Agent, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.generation.logic.constants import PYDANTIC_AI_MODEL
from server.apps.pipelines.schemas import VisualPromptsOutput
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@cache
def _agent() -> Agent[StageContext, VisualPromptsOutput]:
    """Create and cache the visual prompts agent on first call."""
    a: Agent[StageContext, VisualPromptsOutput] = Agent(
        PYDANTIC_AI_MODEL,
        output_type=VisualPromptsOutput,
        deps_type=StageContext,
    )

    @a.system_prompt
    async def _sys(ctx: RunContext[StageContext]) -> str:  # pragma: no cover
        sys, _ = await ctx.deps.prompts.render(
            'visual_prompts',
            {'topic': ctx.deps.run.topic},
        )
        return sys or (
            'You are a visual prompt engineer for AI image generation. '
            'Write Flux-compatible image prompts: specific, evocative, '
            'stylistically consistent with the channel style guide. '
            'Add a negative_prompt to exclude anachronisms. '
            'Flag safety_flagged=true if a prompt may trip content filters.'
        )

    return a


@register_stage
class VisualPromptsStage(Stage):
    """Stage 5: image generation prompts for every scene."""

    key = 'visual_prompts'
    queue = 'api'
    max_retries = 3
    timeout_s = 300

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Write one Flux prompt per scene from the scene breakdown."""
        scenes = ctx.upstream.get('scene_breakdown', {}).get('scenes', [])
        niche = getattr(ctx.channel, 'niche_config', None)
        style = getattr(niche, 'style_guide', '') if niche else ''

        _, usr = await ctx.prompts.render(
            'visual_prompts',
            {
                'scenes': scenes,
                'style_guide': style,
            },
        )
        user_prompt = usr or (
            f'Write image generation prompts for each scene.\n'
            f'Scenes: {scenes}\n'
            f'Style guide: {style or "cinematic, photorealistic, 16:9"}.\n'
            f'Return one VisualPrompt per scene, same order as input scenes.'
        )
        output: VisualPromptsOutput = await llm_client.run_agent(
            _agent(),
            user_prompt,
            ctx,
            stage_key=self.key,
        )
        return output.model_dump()
