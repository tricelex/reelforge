"""Metadata stage — YouTube title, description, tags."""

import operator
from functools import cache
from typing import Any, override

from pydantic_ai import Agent, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.generation.logic.constants import PYDANTIC_AI_MODEL
from server.apps.pipelines.schemas import VideoMetadata
from server.apps.pipelines.services.prompt_variables import (
    build_prompt_variables,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@cache
def _agent() -> Agent[StageContext, VideoMetadata]:
    """Create and cache the metadata agent on first call."""
    a: Agent[StageContext, VideoMetadata] = Agent(
        PYDANTIC_AI_MODEL,
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
) -> str:
    """Build YouTube chapter timestamp string from alignment scene data.

    Alignment ``start_s`` / ``end_s`` are chapter-relative (per TTS file).
    YouTube chapter markers need absolute offsets in the final video, so
    each chapter's duration is summed from its scenes before advancing.
    """
    spans: dict[int, tuple[float, float]] = {}
    for seg in scenes:
        ch_idx = int(seg.get('chapter_idx', 0))
        start_s = float(seg.get('start_s', 0.0))
        end_s = float(seg.get('end_s', start_s))
        if ch_idx not in spans:
            spans[ch_idx] = (start_s, end_s)
        else:
            prev_start, prev_end = spans[ch_idx]
            spans[ch_idx] = (min(prev_start, start_s), max(prev_end, end_s))

    lines: list[str] = []
    offset = 0.0
    for ch in sorted(chapters, key=operator.itemgetter('idx')):
        m = int(offset // 60)
        s = int(offset % 60)
        lines.append(f'{m}:{s:02d} {ch["title"]}')
        if ch['idx'] in spans:
            local_start, local_end = spans[ch['idx']]
            offset += max(0.0, local_end - local_start)
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
        output: VideoMetadata = await llm_client.run_agent(
            _agent(),
            user_prompt,
            ctx,
            stage_key=self.key,
        )
        return output.model_dump()
