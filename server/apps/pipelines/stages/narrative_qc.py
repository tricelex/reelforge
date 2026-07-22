"""Narrative QC stage — LLM-judge creative quality gate before render spend.

Sits between scene_breakdown and visual_prompts/tts. Follows the same failure
convention as the technical `qc` stage: on failure it raises
FatalProviderError (-> NEEDS_INPUT), requiring a human to inspect and rerun
upstream stages. It does not auto-retry script generation itself.
"""

from functools import lru_cache
from typing import Any, override

from pydantic_ai import Agent, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.generation.logic.model_resolver import to_pydantic_ai_model
from server.apps.generation.logic.stage_model import resolve_stage_model
from server.apps.pipelines.schemas import NarrativeQCOutput
from server.apps.pipelines.services.prompt_variables import (
    build_prompt_variables,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError

_PASS_THRESHOLD = 0.5


@lru_cache(maxsize=4)
def _agent(model: str) -> Agent[StageContext, NarrativeQCOutput]:
    """Create and cache the narrative QC agent on first call."""
    a: Agent[StageContext, NarrativeQCOutput] = Agent(
        model,
        output_type=NarrativeQCOutput,
        deps_type=StageContext,
    )

    @a.system_prompt
    async def _sys(ctx: RunContext[StageContext]) -> str:  # pragma: no cover
        variables = await build_prompt_variables(ctx.deps, include_character=False)
        sys, _ = await ctx.deps.prompts.render('narrative_qc', variables)
        return sys or (
            'You are a documentary editorial quality judge. Score this '
            'script + scene breakdown 0.0-1.0 on: (1) does the first 30s '
            'hook restate a real payoff, (2) is there a genuine retention '
            'device (beat, reveal, or question) roughly every 15-30s, '
            "(3) does each chapter's commentary read as real analysis, "
            'not filler that just restates the narration. passed=true only '
            'if score >= 0.5. List specific issues for anything weak.'
        )

    return a


@register_stage
class NarrativeQCStage(Stage):
    """Pre-render creative quality gate."""

    key = 'narrative_qc'
    queue = 'api'
    max_retries = 3
    timeout_s = 180

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Score the script + scene breakdown; raise on failure."""
        script = ctx.upstream.get('script', {})
        scenes = ctx.upstream.get('scene_breakdown', {})

        variables = await build_prompt_variables(ctx, include_character=False)
        _, usr = await ctx.prompts.render('narrative_qc', variables)
        user_prompt = usr or (
            f'Topic: "{ctx.run.topic}"\n'
            f'Script chapters (with commentary): {script.get("chapters", [])}\n'
            f'Scene breakdown: {scenes.get("scenes", [])}\n'
            'Score this and list issues.'
        )
        model_slug = await resolve_stage_model(ctx, self.key)
        output: NarrativeQCOutput = await llm_client.run_agent(
            _agent(to_pydantic_ai_model(model_slug)),
            user_prompt,
            ctx,
            stage_key=self.key,
            model_slug=model_slug,
        )

        if not output.passed or output.score < _PASS_THRESHOLD:
            raise FatalProviderError(
                f'narrative_qc failed: score={output.score:.2f} '
                f'issues={output.issues}',
                provider='narrative_qc',
                error_code='NARRATIVE_QC_FAILED',
            )
        return output.model_dump()
