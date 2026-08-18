"""Visual prompts stage — generates Flux image prompts per scene."""

import uuid
from collections import defaultdict
from functools import lru_cache
from typing import Any, override

from pydantic_ai import Agent, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.generation.logic.model_resolver import to_pydantic_ai_model
from server.apps.generation.logic.stage_model import resolve_stage_model
from server.apps.pipelines.logic.visual_consistency import (
    apply_visual_lock,
    build_visual_lock_prefix,
)
from server.apps.pipelines.schemas import VisualPrompt, VisualPromptsOutput
from server.apps.pipelines.services.prompt_variables import (
    build_prompt_variables,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError


@lru_cache(maxsize=4)
def _agent(model: str) -> Agent[StageContext, VisualPromptsOutput]:
    """Create and cache the visual prompts agent on first call."""
    a: Agent[StageContext, VisualPromptsOutput] = Agent(
        model,
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
            'stylistically consistent. Vary shot type and lens between '
            'adjacent scenes but never change character appearance, '
            'wardrobe, era, or setting identity. '
            'Add a negative_prompt to exclude anachronisms and drift. '
            'Flag safety_flagged=true if a prompt may trip content filters.'
        )

    return a


def _scenes_by_chapter(
    scenes: list[dict[str, Any]],
) -> list[tuple[int, list[dict[str, Any]]]]:
    """Group scenes in first-seen chapter order."""
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    order: list[int] = []
    for scene in scenes:
        chapter_idx = int(scene.get('chapter_idx', 0))
        if chapter_idx not in groups:
            order.append(chapter_idx)
        groups[chapter_idx].append(scene)
    return [(idx, groups[idx]) for idx in order]


def _niche_lock_bits(channel: object) -> tuple[str, str]:
    """Lore and angle from NicheConfig; style_guide does not exist."""
    from django.core.exceptions import ObjectDoesNotExist  # noqa: PLC0415

    try:
        niche = getattr(channel, 'niche_config', None)
    except ObjectDoesNotExist:
        return '', ''
    if niche is None:
        return '', ''
    lore = str(getattr(niche, 'lore_document', '') or '')
    angle = str(getattr(niche, 'angle', '') or '')
    return lore, angle


def _lock_prompt(
    *,
    prompt: VisualPrompt,
    scene: dict[str, Any] | None,
    lore: str,
    angle: str,
    appearance_by_name: dict[str, str],
) -> VisualPrompt:
    """Prepend the code-side visual bible to one LLM prompt."""
    setting = str((scene or {}).get('setting') or '')
    appearance = ''
    for name in (scene or {}).get('foreground_cast') or []:
        appearance = appearance_by_name.get(str(name).casefold(), '')
        if appearance:
            break
    prefix = build_visual_lock_prefix(
        lore=lore,
        angle=angle,
        setting=setting,
        appearance=appearance,
    )
    locked, negative = apply_visual_lock(
        prompt.prompt,
        prefix=prefix,
        negative=prompt.negative_prompt,
    )
    return prompt.model_copy(
        update={'prompt': locked, 'negative_prompt': negative},
    )


def _attach_refs_and_locks(
    prompts: list[VisualPrompt],
    scenes: list[dict[str, Any]],
    *,
    lore: str,
    angle: str,
    cast_locks: dict[str, dict[str, str | None]],
) -> list[VisualPrompt]:
    """Apply visual bible + approved character_ref_id to each prompt."""
    appearance_by_name: dict[str, str] = {}
    for name, lock in cast_locks.items():
        text = lock.get('appearance_prompt')
        if text:
            appearance_by_name[name] = text
    scenes_by_idx = {int(s['idx']): s for s in scenes}
    locked: list[VisualPrompt] = []
    for prompt in prompts:
        scene = scenes_by_idx.get(int(prompt.scene_idx))
        updated = _lock_prompt(
            prompt=prompt,
            scene=scene,
            lore=lore,
            angle=angle,
            appearance_by_name=appearance_by_name,
        )
        locked.append(
            _attach_character_ref(updated, scene, cast_locks),
        )
    return locked


def _attach_character_ref(
    prompt: VisualPrompt,
    scene: dict[str, Any] | None,
    cast_locks: dict[str, dict[str, str | None]],
) -> VisualPrompt:
    """Stamp approved hero_ref onto a prompt that still has none."""
    if prompt.character_ref_id or scene is None:
        return prompt
    for name in scene.get('foreground_cast') or []:
        ref = cast_locks.get(str(name).casefold(), {}).get('character_ref_id')
        if ref:
            return prompt.model_copy(update={'character_ref_id': ref})
    return prompt


@register_stage
class VisualPromptsStage(Stage):
    """Stage 5: image generation prompts for every scene."""

    key = 'visual_prompts'
    queue = 'api'
    max_retries = 3
    timeout_s = 300

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Write one Flux prompt per scene, batched by chapter."""
        scenes = ctx.upstream.get('scene_breakdown', {}).get('scenes', [])
        if not scenes:
            raise FatalProviderError(
                'scene_breakdown has no scenes for visual prompts',
                provider='visual_prompts',
                error_code='missing_scenes',
            )
        lore, angle = _niche_lock_bits(ctx.channel)
        model_slug = await resolve_stage_model(ctx, self.key)
        collected: list[VisualPrompt] = []
        for _chapter_idx, chapter_scenes in _scenes_by_chapter(scenes):
            collected.extend(
                await _prompts_for_chapter(
                    ctx,
                    chapter_scenes,
                    lore=lore,
                    model_slug=model_slug,
                ),
            )
        scene_idxs = {int(s['idx']) for s in scenes}
        prompt_idxs = {int(p.scene_idx) for p in collected}
        if prompt_idxs != scene_idxs:
            missing = sorted(scene_idxs - prompt_idxs)
            extra = sorted(prompt_idxs - scene_idxs)
            raise FatalProviderError(
                f'visual_prompts coverage mismatch — '
                f'missing={missing} extra={extra}',
                provider='visual_prompts',
                error_code='prompt_coverage',
            )
        cast_locks = await _cast_locks(ctx.run.id)
        locked = _attach_refs_and_locks(
            collected,
            scenes,
            lore=lore,
            angle=angle,
            cast_locks=cast_locks,
        )
        return VisualPromptsOutput(prompts=locked).model_dump()


async def _prompts_for_chapter(
    ctx: StageContext,
    chapter_scenes: list[dict[str, Any]],
    *,
    lore: str,
    model_slug: str,
) -> list[VisualPrompt]:
    """One LLM call for the scenes in a single chapter."""
    variables = await build_prompt_variables(
        ctx,
        extra={
            'style_guide': lore,
            'chapter_scenes': chapter_scenes,
        },
    )
    _, usr = await ctx.prompts.render('visual_prompts', variables)
    user_prompt = usr or (
        f'Write image generation prompts for each scene.\n'
        f'Scenes: {chapter_scenes}\n'
        f'Style guide: {lore or "cinematic, photorealistic, 16:9"}.\n'
        f'Vary camera and lens; keep setting and character identity locked.\n'
        f'Return one VisualPrompt per scene, same order as input scenes.'
    )
    output: VisualPromptsOutput = await llm_client.run_agent(
        _agent(to_pydantic_ai_model(model_slug)),
        user_prompt,
        ctx,
        stage_key='visual_prompts',
        model_slug=model_slug,
    )
    return list(output.prompts)


async def _cast_locks(run_id: object) -> dict[str, dict[str, str | None]]:
    """Map character name → appearance text and optional hero_ref id.

    Appearance comes from any RunCast so skipped/none-mode gates still
    text-lock. character_ref_id is only set for approved hero sheets.
    """
    try:
        run_uuid = uuid.UUID(str(run_id))
    except ValueError:
        return {}
    from server.apps.pipelines.models import (  # noqa: PLC0415
        CastDesignStatus,
        RunCast,
    )

    rows = [
        row
        async for row in RunCast.objects.filter(
            run_id=run_uuid,
        ).select_related(
            'character',
        )
    ]
    mapping: dict[str, dict[str, str | None]] = {}
    for row in rows:
        name = row.character.name.casefold()
        appearance = row.character.appearance_prompt or row.draft_prompt or ''
        ref_id = None
        if (
            row.design_status == CastDesignStatus.APPROVED
            and row.character.hero_ref_id
        ):
            ref_id = str(row.character.hero_ref_id)
        mapping[name] = {
            'appearance_prompt': appearance,
            'character_ref_id': ref_id,
        }
    return mapping
