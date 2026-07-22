"""Metadata stage — YouTube title, description, tags."""

import operator
from functools import lru_cache
from typing import Any, override

from pydantic_ai import Agent, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.generation.logic.model_resolver import to_pydantic_ai_model
from server.apps.generation.logic.stage_model import resolve_stage_model
from server.apps.pipelines.schemas import VideoMetadata
from server.apps.pipelines.services.prompt_variables import (
    build_prompt_variables,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@lru_cache(maxsize=4)
def _agent(model: str) -> Agent[StageContext, VideoMetadata]:
    """Create and cache the metadata agent on first call."""
    a: Agent[StageContext, VideoMetadata] = Agent(
        model,
        output_type=VideoMetadata,
        deps_type=StageContext,
    )

    @a.system_prompt
    async def _sys(ctx: RunContext[StageContext]) -> str:  # pragma: no cover
        variables = await build_prompt_variables(ctx.deps, include_character=False)
        sys, _ = await ctx.deps.prompts.render('metadata', variables)
        return sys or (
            'You are a YouTube SEO specialist. '
            'Write a title ≤60 chars (hook-style, no clickbait lies), '
            'a description with YouTube chapter timestamps, '
            'and 10-15 tags. Category is usually Education or Entertainment.'
        )

    return a


def _build_chapter_timestamps(
    scenes: list[dict[str, Any]],
    chapters: list[dict[str, Any]],
    *,
    transition_s: float = 0.5,
) -> str:
    """Build YouTube chapter timestamp string from absolute alignment scenes.

    Alignment ``start_s`` / ``end_s`` are absolute on the narration timeline.
    Assembly inserts ``transition_s`` between scenes within a chapter, so
    markers add cumulative transition padding to match the final mux.
    """
    chapter_starts: dict[int, float] = {}
    scenes_per_chapter: dict[int, int] = {}
    for seg in scenes:
        ch_idx = int(seg.get('chapter_idx', 0))
        start_s = float(seg.get('start_s', 0.0))
        if ch_idx not in chapter_starts:
            chapter_starts[ch_idx] = start_s
        else:
            chapter_starts[ch_idx] = min(chapter_starts[ch_idx], start_s)
        scenes_per_chapter[ch_idx] = scenes_per_chapter.get(ch_idx, 0) + 1

    lines: list[str] = []
    transition_pad = 0.0
    for ch in sorted(chapters, key=operator.itemgetter('idx')):
        abs_start = chapter_starts.get(ch['idx'], 0.0)
        offset = abs_start + transition_pad
        m = int(offset // 60)
        s = int(offset % 60)
        lines.append(f'{m}:{s:02d} {ch["title"]}')
        n_scenes = scenes_per_chapter.get(ch['idx'], 0)
        transition_pad += max(0, n_scenes - 1) * transition_s
    return '\n'.join(lines)


@register_stage
class MetadataStage(Stage):
    """Stage 12: YouTube metadata generation (title, description, tags)."""

    key = 'metadata'
    queue = 'api'
    max_retries = 3
    timeout_s = 120

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Generate YouTube-optimised metadata for the completed video."""
        chapters = ctx.upstream.get('script', {}).get('chapters', [])
        alignment_scenes = ctx.upstream.get('alignment', {}).get('scenes', [])
        timestamps = _build_chapter_timestamps(alignment_scenes, chapters)

        variables = await build_prompt_variables(
            ctx,
            extra={'timestamps': timestamps},
            include_character=False,
        )
        _, usr = await ctx.prompts.render('metadata', variables)
        user_prompt = usr or (
            f'Write YouTube metadata for "{ctx.run.topic}".\n'
            f'Chapter timestamps:\n{timestamps}\n'
            f'Title: ≤60 chars, hook-style.\n'
            f'Description: intro paragraph + timestamps block '
            f'+ call to action.\n'
            f'Tags: 10-15 relevant tags.'
        )
        model_slug = await resolve_stage_model(ctx, self.key)
        output: VideoMetadata = await llm_client.run_agent(
            _agent(to_pydantic_ai_model(model_slug)),
            user_prompt,
            ctx,
            stage_key=self.key,
            model_slug=model_slug,
        )
        return output.model_dump()
