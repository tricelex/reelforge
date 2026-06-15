"""Scene breakdown stage — chapters split into scenes with validation."""

from functools import cache
from typing import Any, override

from pydantic_ai import Agent, ModelRetry, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.pipelines.schemas import SceneBreakdownOutput
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@cache
def _agent() -> Agent[StageContext, SceneBreakdownOutput]:  # noqa: C901
    """Create and cache the scene breakdown agent on first call."""
    a: Agent[StageContext, SceneBreakdownOutput] = Agent(
        'anthropic:claude-opus-4-8',
        output_type=SceneBreakdownOutput,
        deps_type=StageContext,
    )

    @a.system_prompt
    async def _sys(ctx: RunContext[StageContext]) -> str:  # pragma: no cover
        sys, _ = await ctx.deps.prompts.render(
            'scene_breakdown',
            {'topic': ctx.deps.run.topic},
        )
        return sys or (
            'You are a documentary scene breakdown specialist. '
            'Split each chapter into scenes of 6-12 seconds of narration. '
            'Each scene narration_text must be 10-35 words '
            '(word_count in [10, 35]). '
            'Assign is_hero=true to ~15% of scenes '
            '(hooks, chapter opens, climaxes). '
            'foreground_cast must list ≤2 characters per scene. '
            'Return valid JSON matching the SceneBreakdownOutput schema.'
        )

    @a.output_validator
    def _validate(  # pragma: no cover
        ctx: RunContext[StageContext],
        output: SceneBreakdownOutput,
    ) -> SceneBreakdownOutput:
        """Enforce scene invariants; raise ModelRetry for self-correction."""
        errors: list[str] = []
        for scene in output.scenes:
            if not (10 <= scene.word_count <= 35):
                errors.append(
                    f'scene {scene.idx}: word_count='
                    f'{scene.word_count} must be in [10,35]',
                )
            if len(scene.foreground_cast) > 2:
                errors.append(
                    f'scene {scene.idx}: '
                    f'{len(scene.foreground_cast)} foreground chars (max 2)',
                )
        if errors:
            raise ModelRetry('Fix invariant violations:\n' + '\n'.join(errors))
        return output

    return a


@register_stage
class SceneBreakdownStage(Stage):
    """Stage 4: scene-level breakdown for all chapters."""

    key = 'scene_breakdown'
    queue = 'api'
    max_retries = 3
    timeout_s = 300

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Break the script into individual visual scenes."""
        chapters = ctx.upstream.get('script', {}).get('chapters', [])
        hero_ratio = ctx.config.get('hero_ratio', 0.15)

        _, usr = await ctx.prompts.render(
            'scene_breakdown',
            {
                'topic': ctx.run.topic,
                'chapters': chapters,
                'hero_ratio': hero_ratio,
            },
        )
        user_prompt = usr or (
            f'Break down each chapter of "{ctx.run.topic}" into scenes.\n'
            f'Chapters: {chapters}\n'
            f'Target hero_ratio: {hero_ratio} '
            f'(mark ~{int(hero_ratio * 100)}% scenes as is_hero=true).\n'
            f'Each scene: idx, chapter_idx, beat, narration_text, '
            f'visual_concept, shot_type, est_seconds (6-12), is_hero, '
            f'foreground_cast (≤2 names), word_count (word count).'
        )
        output: SceneBreakdownOutput = await llm_client.run_agent(
            _agent(),
            user_prompt,
            ctx,
            stage_key=self.key,
        )
        return output.model_dump()
