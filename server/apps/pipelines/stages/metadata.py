"""Metadata stage — YouTube title, description, tags."""

import operator
from functools import cache
from typing import Any, override

from pydantic_ai import Agent, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.pipelines.schemas import VideoMetadata
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@cache
def _agent() -> Agent[StageContext, VideoMetadata]:
    """Create and cache the metadata agent on first call."""
    a: Agent[StageContext, VideoMetadata] = Agent(
        'anthropic:claude-opus-4-8',
        output_type=VideoMetadata,
        deps_type=StageContext,
    )

    @a.system_prompt
    async def _sys(ctx: RunContext[StageContext]) -> str:  # pragma: no cover
        sys, _ = await ctx.deps.prompts.render(
            'metadata',
            {'topic': ctx.deps.run.topic},
        )
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
    """Build YouTube chapter timestamp string from alignment scene data."""
    chapter_starts: dict[int, float] = {}
    for seg in scenes:
        ch_idx = seg.get('chapter_idx', 0)
        if ch_idx not in chapter_starts:
            chapter_starts[ch_idx] = seg.get('start_s', 0.0)

    lines: list[str] = []
    for ch in sorted(chapters, key=operator.itemgetter('idx')):
        start_s = chapter_starts.get(ch['idx'], 0.0)
        m = int(start_s // 60)
        s = int(start_s % 60)
        lines.append(f'{m}:{s:02d} {ch["title"]}')
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

        _, usr = await ctx.prompts.render(
            'metadata',
            {
                'topic': ctx.run.topic,
                'chapters': chapters,
                'timestamps': timestamps,
            },
        )
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
