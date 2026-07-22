"""Visual prompts stage — generates Flux image prompts per scene."""

from functools import cache
from typing import Any, override

from pydantic_ai import Agent, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.generation.logic.constants import PYDANTIC_AI_MODEL
from server.apps.pipelines.schemas import VisualPromptsOutput
from server.apps.pipelines.services.prompt_variables import (
    build_prompt_variables,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError


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
        variables = await build_prompt_variables(ctx.deps)
        sys, _ = await ctx.deps.prompts.render('visual_prompts', variables)
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

        variables = await build_prompt_variables(
            ctx,
            extra={'style_guide': style},
        )
        _, usr = await ctx.prompts.render('visual_prompts', variables)
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
        prompts = output.prompts
        scene_idxs = {int(s['idx']) for s in scenes}
        prompt_idxs = {int(p.scene_idx) for p in prompts}
        if not scenes:
            raise FatalProviderError(
                'scene_breakdown has no scenes for visual prompts',
                provider='visual_prompts',
                error_code='missing_scenes',
            )
        if prompt_idxs != scene_idxs:
            missing = sorted(scene_idxs - prompt_idxs)
            extra = sorted(prompt_idxs - scene_idxs)
            raise FatalProviderError(
                f'visual_prompts coverage mismatch — '
                f'missing={missing} extra={extra}',
                provider='visual_prompts',
                error_code='prompt_coverage',
            )
        return output.model_dump()
