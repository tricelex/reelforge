"""Footage queries stage — turns scenes into provider search terms."""

from functools import lru_cache
from typing import Any, override

from pydantic_ai import Agent, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.generation.logic.model_resolver import to_pydantic_ai_model
from server.apps.generation.logic.stage_model import resolve_stage_model
from server.apps.pipelines.schemas import FootageQueriesOutput
from server.apps.pipelines.services.prompt_variables import (
    build_prompt_variables,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError

_FALLBACK_SYSTEM = (
    'You write search queries for stock and public-domain footage '
    'libraries. For each scene, produce a primary_query of 2-5 concrete '
    'visual nouns describing an archetypal, findable shot — subject, '
    'action, setting. Never name individuals, specific dated events, or '
    'anything unique enough that no library would hold it. Add 2-3 '
    'progressively broader fallback_queries. Set media_preference to '
    '"video" for motion-led scenes and "image" for archival or static '
    'ones. Use era_hint for period material. Always write an '
    'ai_fallback_prompt describing the shot for an image generator, used '
    'only when no footage is found.'
)


@lru_cache(maxsize=4)
def _agent(model: str) -> Agent[StageContext, FootageQueriesOutput]:
    """Create and cache the footage queries agent on first call."""
    a: Agent[StageContext, FootageQueriesOutput] = Agent(
        model,
        output_type=FootageQueriesOutput,
        deps_type=StageContext,
    )

    @a.system_prompt
    async def _sys(ctx: RunContext[StageContext]) -> str:  # pragma: no cover
        variables = await build_prompt_variables(
            ctx.deps,
            include_character=False,
        )
        sys, _ = await ctx.deps.prompts.render('footage_queries', variables)
        return sys or _FALLBACK_SYSTEM

    return a


@register_stage
class FootageQueriesStage(Stage):
    """Documentary stage: search terms for every scene."""

    key = 'footage_queries'
    queue = 'api'
    max_retries = 3
    timeout_s = 300

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Write provider search queries for each scene."""
        scenes = ctx.upstream.get('scene_breakdown', {}).get('scenes', [])
        if not scenes:
            raise FatalProviderError(
                'scene_breakdown has no scenes for footage queries',
                provider='footage_queries',
                error_code='missing_scenes',
            )

        variables = await build_prompt_variables(
            ctx,
            include_character=False,
        )
        _, usr = await ctx.prompts.render('footage_queries', variables)
        user_prompt = usr or (
            f'Write footage search queries for "{ctx.run.topic}".\n'
            f'Scenes: {scenes}\n'
            f'Return one FootageQuery per scene, same scene_idx values.'
        )
        model_slug = await resolve_stage_model(ctx, self.key)
        output: FootageQueriesOutput = await llm_client.run_agent(
            _agent(to_pydantic_ai_model(model_slug)),
            user_prompt,
            ctx,
            stage_key=self.key,
            model_slug=model_slug,
        )

        scene_idxs = {int(s['idx']) for s in scenes}
        query_idxs = {int(q.scene_idx) for q in output.queries}
        if query_idxs != scene_idxs:
            missing = sorted(scene_idxs - query_idxs)
            extra = sorted(query_idxs - scene_idxs)
            raise FatalProviderError(
                f'footage_queries coverage mismatch — '
                f'missing={missing} extra={extra}',
                provider='footage_queries',
                error_code='query_coverage',
            )
        return output.model_dump()
