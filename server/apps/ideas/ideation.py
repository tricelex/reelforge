"""LLM-powered topic ideation — single structured call, pre-fetched context."""

import json
from functools import cache
from typing import TYPE_CHECKING

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel

from server.apps.generation.logic.constants import DEFAULT_LLM_MODEL
from server.apps.ideas.logic.schemas import (
    IdeationOutput,
    OutlierVideo,
    SourceSnapshot,
)

if TYPE_CHECKING:
    from server.apps.ideas.selectors import IdeationContext

_AGENT_BUFFER = 2
_SYSTEM_PROMPT = (
    'You are an expert YouTube content strategist for longform educational '
    'channels. Propose distinct video ideas that fit the niche, avoid overlap '
    'with recent topics, and respect banned topics. For remix mode, steal '
    'structure and hook patterns from the source — do not paraphrase the '
    'transcript. Each idea needs a clear differentiation angle. Return JSON '
    'with an "ideas" array.'
)


@cache
def _agent() -> Agent[None, IdeationOutput]:
    return Agent(
        OpenAIChatModel(DEFAULT_LLM_MODEL),
        output_type=IdeationOutput,
        system_prompt=_SYSTEM_PROMPT,
    )


def _context_lines(context: 'IdeationContext') -> list[str]:
    """Header lines describing the niche configuration."""
    lines: list[str] = []
    if context.format_name:
        lines.append(f'Story format: {context.format_name}')
    if context.lore_document:
        lines.append(f'Channel lore:\n{context.lore_document[:2000]}')
    if context.banned_topics:
        banned = json.dumps(context.banned_topics)
        lines.append(f'Never propose topics touching: {banned}')
    if context.existing_topics:
        recent = json.dumps(sorted(context.existing_topics)[:40])
        lines.append(f'Avoid overlap with these recent topics: {recent}')
    return lines


def _source_lines(source: SourceSnapshot) -> list[str]:
    """Remix-mode block describing the source video."""
    views = source.view_count if source.view_count is not None else 'unknown'
    return [
        '',
        'REMIX MODE — source video:',
        f'Title: {source.title}',
        f'Channel: {source.channel}',
        f'Duration (sec): {source.duration_sec:.0f}',
        f'Views: {views}',
        f'URL: {source.url}',
        f'Description:\n{source.description[:1500]}',
        f'Captions excerpt:\n{source.caption_text[:3000]}',
        (
            'Propose remix angles: contrarian takes, deeper dives, '
            'niche-localized versions, or structural hook swaps.'
        ),
    ]


def _trending_lines(outliers: list[OutlierVideo]) -> list[str]:
    """Niche-only demand-signal block built from real outlier data."""
    lines = ['', 'TRENDING IN YOUR NICHE (real YouTube data):']
    lines.extend(
        f'- "{o.title}" ({o.channel_title}, {o.view_count:,} views, '
        f'outlier score {o.outlier_score:.2f})'
        for o in outliers[:10]
    )
    lines.append(
        'Use these as demand signal — propose ideas that share the '
        "underlying appeal (angle, hook pattern, or gap) with what's "
        'already resonating, without copying any single video.',
    )
    return lines


def _build_prompt(
    context: 'IdeationContext',
    source: SourceSnapshot | None,
    count: int,
    outliers: list[OutlierVideo] | None = None,
) -> str:
    request_count = min(count + _AGENT_BUFFER, 22)
    lines = [
        f'Generate {request_count} unique longform video ideas.',
        f'Channel audience: {context.audience or "general"}',
        f'Channel angle: {context.angle or "educational"}',
    ]
    lines.extend(_context_lines(context))

    if source is not None:
        lines.extend(_source_lines(source))
    else:
        lines.append(
            'NICHE-ONLY MODE — invent fresh angles from audience and angle.',
        )
        if outliers:
            lines.extend(_trending_lines(outliers))

    lines.append(
        'Each idea: title (<=120 chars), topic (run seed, 1-3 sentences), '
        'score 0.0-1.0, remix_strategy, hook_pattern, differentiation, '
        'source_refs (empty list if niche-only).',
    )
    return '\n'.join(lines)


def run_ideation_agent(
    context: 'IdeationContext',
    *,
    source: SourceSnapshot | None,
    count: int,
    outliers: list[OutlierVideo] | None = None,
) -> IdeationOutput:
    """Run one bounded ideation LLM call and return structured candidates."""
    prompt = _build_prompt(context, source, count, outliers=outliers)
    result = _agent().run_sync(prompt)
    return result.output
