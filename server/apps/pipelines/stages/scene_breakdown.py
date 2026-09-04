"""Scene breakdown stage — chapters split into scenes with validation."""

from functools import lru_cache
from typing import Any, override

from pydantic_ai import Agent, ModelRetry, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.generation.logic.model_resolver import to_pydantic_ai_model
from server.apps.generation.logic.stage_model import resolve_stage_model
from server.apps.pipelines.logic.scene_density import (
    chapter_word_count,
    clamp_hero_flags,
    coverage_limits,
    coverage_ok,
    density_bounds,
    max_hero_scenes,
    stitch_global_idx,
)
from server.apps.pipelines.schemas import SceneBreakdownOutput
from server.apps.pipelines.services.prompt_variables import (
    build_prompt_variables,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError

_MAX_CHAPTER_ATTEMPTS = 3


@lru_cache(maxsize=4)
def _agent(model: str) -> Agent[StageContext, SceneBreakdownOutput]:  # noqa: C901
    """Create and cache the scene breakdown agent on first call."""
    a: Agent[StageContext, SceneBreakdownOutput] = Agent(
        model,
        output_type=SceneBreakdownOutput,
        deps_type=StageContext,
        retries={'output': 3},
    )

    @a.system_prompt
    async def _sys(ctx: RunContext[StageContext]) -> str:  # pragma: no cover
        variables = await build_prompt_variables(ctx.deps)
        sys = await ctx.deps.prompts.render_system(
            'scene_breakdown',
            variables,
        )
        min_w, max_w, min_s, max_s = density_bounds(ctx.deps.config)
        return sys or (
            'You are a documentary scene breakdown specialist. '
            f'Split each chapter into scenes of {min_s:g}-{max_s:g} '
            'seconds of narration. '
            f'Each scene narration_text must be {min_w}-{max_w} words '
            f'(word_count in [{min_w}, {max_w}]). '
            'narration_text must be contiguous verbatim slices of the '
            'chapter text covering the whole chapter in order. '
            'Assign is_hero=true only to hooks, chapter opens, climaxes. '
            'foreground_cast must list ≤2 characters per scene. '
            'Keep setting stable across adjacent scenes in one location. '
            'Also emit a top-level cast list of distinct characters '
            'the script implies (name, role, importance, appearance_brief). '
            'Use empty cast when the niche has no visual protagonists '
            '(e.g. pure history explainers). '
            'Return valid JSON matching the SceneBreakdownOutput schema.'
        )

    @a.output_validator
    def _validate(  # pragma: no cover
        ctx: RunContext[StageContext],
        output: SceneBreakdownOutput,
    ) -> SceneBreakdownOutput:
        """Enforce scene invariants; raise ModelRetry for self-correction."""
        min_w, max_w, min_s, max_s = density_bounds(ctx.deps.config)
        errors: list[str] = []
        for scene in output.scenes:
            if not (min_w <= scene.word_count <= max_w):
                errors.append(
                    f'scene {scene.idx}: word_count='
                    f'{scene.word_count} must be in [{min_w},{max_w}]',
                )
            if not (min_s <= scene.est_seconds <= max_s):
                errors.append(
                    f'scene {scene.idx}: est_seconds='
                    f'{scene.est_seconds} must be in [{min_s:g},{max_s:g}]',
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


def _fallback_chapter_prompt(
    topic: str,
    chapter: dict[str, Any],
    hero_ratio: float,
    min_w: int,
    max_w: int,
    min_s: float,
    max_s: float,
    coverage_note: str,
) -> str:
    """User prompt used when the DB template is empty."""
    note = f'\nCoverage fix: {coverage_note}\n' if coverage_note else ''
    return (
        f'Break chapter {chapter.get("idx")} of "{topic}" into scenes.\n'
        f'Chapter: {chapter}\n'
        f'{note}'
        f'Target hero_ratio: {hero_ratio} '
        f'(mark ~{int(hero_ratio * 100)}% scenes as is_hero=true).\n'
        f'narration_text must be a contiguous verbatim slice of the '
        f'chapter text. Cover the whole chapter in order.\n'
        f'Each scene: idx, chapter_idx, beat, narration_text, '
        f'visual_concept, shot_type, setting, '
        f'est_seconds ({min_s:g}-{max_s:g}), is_hero, '
        f'foreground_cast (≤2 names), word_count ({min_w}-{max_w}).\n'
        f'Also return cast: distinct characters with name, role, '
        f'importance (main|secondary|background), appearance_brief. '
        f'Empty cast is correct when no visual protagonists are needed.'
    )


async def _breakdown_chapter(
    ctx: StageContext,
    chapter: dict[str, Any],
    *,
    hero_ratio: float,
    model_slug: str,
) -> SceneBreakdownOutput:
    """Run the agent for one chapter, retrying on coverage failure."""
    min_w, max_w, min_s, max_s = density_bounds(ctx.config)
    ratio_min, ratio_max = coverage_limits(ctx.config)
    chapter_words = chapter_word_count(str(chapter.get('text', '')))
    coverage_note = ''
    for _attempt in range(_MAX_CHAPTER_ATTEMPTS):
        variables = await build_prompt_variables(
            ctx,
            extra={
                'hero_ratio': hero_ratio,
                'chapter': chapter,
                'coverage_note': coverage_note,
            },
        )
        _, usr = await ctx.prompts.render('scene_breakdown', variables)
        user_prompt = usr or _fallback_chapter_prompt(
            ctx.run.topic,
            chapter,
            hero_ratio,
            min_w,
            max_w,
            min_s,
            max_s,
            coverage_note,
        )
        output: SceneBreakdownOutput = await llm_client.run_agent(
            _agent(to_pydantic_ai_model(model_slug)),
            user_prompt,
            ctx,
            stage_key='scene_breakdown',
            model_slug=model_slug,
            request_limit=5,
        )
        word_sum = sum(scene.word_count for scene in output.scenes)
        if coverage_ok(word_sum, chapter_words, ratio_min, ratio_max):
            return output
        coverage_note = (
            f'covered {word_sum} of {chapter_words} chapter words; '
            f'resplit into {min_w}-{max_w} word verbatim slices'
        )
    raise FatalProviderError(
        f'Chapter {chapter.get("idx")}: {coverage_note}',
        provider='scene_breakdown',
        error_code='scene_coverage',
    )


def _union_cast(
    members: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deduplicate cast by casefolded name, first occurrence wins."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for member in members:
        name = str(member.get('name', '')).strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(member)
    return out


@register_stage
class SceneBreakdownStage(Stage):
    """Stage 4: scene-level breakdown for all chapters."""

    key = 'scene_breakdown'
    queue = 'api'
    max_retries = 3
    timeout_s = 1800

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Break the script into individual visual scenes per chapter."""
        chapters = ctx.upstream.get('script', {}).get('chapters', [])
        if not chapters:
            raise FatalProviderError(
                'script has no chapters for scene breakdown',
                provider='scene_breakdown',
                error_code='missing_chapters',
            )
        hero_ratio = ctx.config.get('hero_ratio', 0.15)
        model_slug = await resolve_stage_model(ctx, self.key)
        per_chapter: list[list[dict[str, Any]]] = []
        cast_rows: list[dict[str, Any]] = []
        for chapter in chapters:
            output = await _breakdown_chapter(
                ctx,
                chapter,
                hero_ratio=float(hero_ratio),
                model_slug=model_slug,
            )
            chapter_idx = int(chapter['idx'])
            dumped = [
                {**scene.model_dump(), 'chapter_idx': chapter_idx}
                for scene in output.scenes
            ]
            per_chapter.append(dumped)
            cast_rows.extend(m.model_dump() for m in output.cast)
        scenes = stitch_global_idx(per_chapter)
        hero_cap = max_hero_scenes(ctx.config)
        if hero_cap is not None:
            scenes = clamp_hero_flags(scenes, hero_cap)
        if not scenes:
            raise FatalProviderError(
                'scene_breakdown produced no scenes',
                provider='scene_breakdown',
                error_code='missing_scenes',
            )
        return {'scenes': scenes, 'cast': _union_cast(cast_rows)}
