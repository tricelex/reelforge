"""EditorBrief stage — LLM editorial brief + deterministic appendix.

The agent writes Resolve-facing editorial guidance (tone, pacing, must-hit
beats, caption/music notes). A deterministic appendix still lists chapters,
scenes, music bed ids, and approved clip candidates so facts stay exact on
rebuild.
"""

import json
from functools import lru_cache
from typing import TYPE_CHECKING, Any, override

from pydantic_ai import Agent, RunContext

from server.apps.generation.clients import llm as llm_client
from server.apps.generation.logic.model_resolver import to_pydantic_ai_model
from server.apps.generation.logic.stage_model import resolve_stage_model
from server.apps.pipelines.logic.editor_handoff import is_clipping_run
from server.apps.pipelines.schemas import EditorBriefOutput
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)

if TYPE_CHECKING:
    from server.apps.clips.models import ClipCandidate

_MAX_SCENES = 2000
_MAX_CANDIDATES = 500
_MAX_PROMPT_CHARS = 12_000


def _fmt_mmss(seconds: float) -> str:
    """Format seconds as M:SS for human-readable brief text."""
    assert seconds >= 0, f'seconds must be >= 0, got {seconds}'  # noqa: S101
    total = round(seconds)
    minutes, secs = divmod(total, 60)
    return f'{minutes}:{secs:02d}'


def _chapter_lines(chapters: list[dict[str, Any]]) -> list[str]:
    """Render one bullet per chapter, including its closing line."""
    lines: list[str] = ['## Appendix — Chapters', '']
    for ch in chapters:
        title = str(ch.get('title', f'Chapter {ch.get("idx", "?")}'))
        lines.append(f'- **{title}**')
        closing = str(ch.get('closing_line', '')).strip()
        if closing:
            lines.append(f'  - Closing line: "{closing}"')
    lines.append('')
    return lines


def _scene_lines(scenes: list[dict[str, Any]]) -> list[str]:
    """Render one bullet per scene: beat, visual concept, hero flag."""
    assert len(scenes) <= _MAX_SCENES, (  # noqa: S101
        'scene count exceeded bound'
    )
    lines: list[str] = ['## Appendix — Scene Intents', '']
    for i, scene in enumerate(scenes):
        assert i < _MAX_SCENES, 'scene index exceeded bound'  # noqa: S101
        idx = scene.get('idx', i)
        hero = ' (HERO)' if scene.get('is_hero') else ''
        beat = str(scene.get('beat', '')).strip()
        visual = str(scene.get('visual_concept', '')).strip()
        lines.append(f'- Scene {idx}{hero}: {beat}'.rstrip(': '))
        if visual:
            lines.append(f'  - Visual: {visual}')
    lines.append('')
    return lines


def _music_lines(music_plan: dict[str, Any]) -> list[str]:
    """Render the music bed note block."""
    library_asset_id = music_plan.get('library_asset_id')
    lines: list[str] = ['## Appendix — Music Notes', '']
    if not library_asset_id:
        lines.append('- No background music bed selected for this run.')
    else:
        gain_db = music_plan.get('gain_db', -22.0)
        lines.extend((
            f'- Library asset: `{library_asset_id}`',
            f'- Suggested bed gain: {gain_db} dB',
        ))
    lines.append('')
    return lines


def _build_longform_appendix(ctx: StageContext) -> str:
    """Build the deterministic longform appendix markdown."""
    script = ctx.upstream.get('script', {})
    chapters = script.get('chapters', [])
    scenes = ctx.upstream.get('scene_breakdown', {}).get('scenes', [])
    music_plan = ctx.upstream.get('music_plan', {})
    lines: list[str] = []
    lines.extend(_chapter_lines(chapters))
    lines.extend(_scene_lines(scenes))
    lines.extend(_music_lines(music_plan))
    return '\n'.join(lines)


def _beat_cut_lines(beats: object) -> list[str]:
    """Render numbered Hook/Story/Payoff cut lines for the appendix."""
    if not isinstance(beats, list) or not beats:
        return []
    role_labels = {
        'hook': 'HOOK',
        'story': 'STORY',
        'payoff': 'PAYOFF',
    }
    lines: list[str] = []
    max_beats = 3
    for idx, beat in enumerate(beats[:max_beats]):
        assert idx < max_beats  # noqa: S101
        if not isinstance(beat, dict):
            continue
        role = str(beat.get('role', '')).lower()
        label = role_labels.get(role, role.upper() or f'BEAT{idx + 1}')
        b_start = _fmt_mmss(float(beat.get('start_sec', 0) or 0))
        b_end = _fmt_mmss(float(beat.get('end_sec', 0) or 0))
        note = str(beat.get('note', '') or '').strip()
        beat_line = f'  - {idx + 1}. {label} [{b_start}-{b_end}]'
        if note:
            beat_line += f' - {note}'
        lines.append(beat_line)
    return lines


def _candidate_line(candidate: 'ClipCandidate') -> str:
    """Render one candidate's markdown cut sheet with Hook/Story/Payoff."""
    start = _fmt_mmss(candidate.start_sec)
    end = _fmt_mmss(candidate.end_sec)
    title = candidate.title or 'Untitled clip'
    hook = candidate.hook_text
    arrangement = getattr(candidate, 'arrangement', '') or 'contiguous'
    scores = (
        f'relevance={candidate.relevance_score:.2f} '
        f'virality={candidate.virality_score:.2f} '
        f'hook={candidate.hook_score:.2f}'
    )
    parts = [
        (
            f'- **{title}** envelope [{start}-{end}] '
            f'({candidate.status}, {arrangement})'
        ),
    ]
    if hook:
        parts.append(f'  - Hook overlay: "{hook}"')
    parts.append('  - Playback: Hook → Story → Payoff')
    beat_lines = _beat_cut_lines(getattr(candidate, 'beats', None))
    parts.extend(beat_lines)
    if beat_lines:
        if arrangement == 'cold_open':
            parts.append(
                '  - Join: hard cut Hook teaser → Story → Payoff; '
                'land on payoff breath; never mid-word',
            )
        else:
            parts.append(
                '  - Join: trim contiguous Hook→Story→Payoff; '
                'hard cuts on breaths; never mid-word',
            )
    parts.append(f'  - Scores: {scores}')
    return '\n'.join(parts)


async def _load_approved_candidates(
    ctx: StageContext,
) -> list['ClipCandidate']:
    """Fetch approved ClipCandidate rows ordered by start time."""
    from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

    approved_ids: list[str] = ctx.upstream.get(
        'clip_approval_gate',
        {},
    ).get('approved_candidate_ids', [])
    if not approved_ids:
        return []
    candidates = [
        c
        async for c in ClipCandidate.objects.filter(
            id__in=approved_ids,
        ).order_by('start_sec')
    ]
    assert len(candidates) <= _MAX_CANDIDATES, (  # noqa: S101
        'candidate count exceeded bound'
    )
    return candidates


async def _build_clipping_appendix(ctx: StageContext) -> str:
    """Build the deterministic clipping appendix markdown."""
    candidates = await _load_approved_candidates(ctx)
    lines: list[str] = ['## Appendix — Approved Candidates', '']
    if not candidates:
        lines.append('- No candidates were approved for this run.')
    for i, candidate in enumerate(candidates):
        assert i < _MAX_CANDIDATES, (  # noqa: S101
            'candidate index exceeded bound'
        )
        lines.append(_candidate_line(candidate))
    lines.append('')
    return '\n'.join(lines)


def _bullet_section(title: str, items: list[str]) -> list[str]:
    """Render a markdown section from a list of strings."""
    lines: list[str] = [f'## {title}', '']
    if not items:
        lines.append('- (none)')
    else:
        lines.extend(f'- {item}' for item in items)
    lines.append('')
    return lines


def _render_editorial_markdown(
    topic: str,
    editorial: EditorBriefOutput,
) -> str:
    """Render the LLM editorial front matter as markdown."""
    assert topic, 'topic is required'  # noqa: S101
    assert editorial.summary.strip(), 'summary must not be empty'  # noqa: S101
    lines: list[str] = [
        f'# Edit Brief — {topic}',
        '',
        '## Editorial summary',
        '',
        editorial.summary.strip(),
        '',
        '## Tone and pacing',
        '',
        editorial.tone_and_pacing.strip(),
        '',
    ]
    lines.extend(_bullet_section('Must-hit beats', editorial.must_hit_beats))
    lines.extend(
        _bullet_section('Optional emphasis', editorial.optional_emphasis),
    )
    if editorial.caption_guidance.strip():
        lines.extend((
            '## Caption guidance',
            '',
            editorial.caption_guidance.strip(),
            '',
        ))
    if editorial.music_and_silence.strip():
        lines.extend((
            '## Music and silence',
            '',
            editorial.music_and_silence.strip(),
            '',
        ))
    lines.extend(_bullet_section('Resolve — do', editorial.resolve_dos))
    lines.extend(
        _bullet_section('Resolve — do not', editorial.resolve_donts),
    )
    if editorial.beat_notes:
        lines.extend(('## Beat notes', ''))
        lines.extend(
            f'- **{note.label}**: {note.note}' for note in editorial.beat_notes
        )
        lines.append('')
    return '\n'.join(lines)


def _longform_context_payload(ctx: StageContext) -> dict[str, Any]:
    """Compact longform facts for the agent user prompt."""
    script = ctx.upstream.get('script', {})
    scenes = ctx.upstream.get('scene_breakdown', {}).get('scenes', [])
    music_plan = ctx.upstream.get('music_plan', {})
    return {
        'topic': ctx.run.topic,
        'chapters': [
            {
                'idx': ch.get('idx'),
                'title': ch.get('title'),
                'closing_line': ch.get('closing_line'),
            }
            for ch in script.get('chapters', [])[:40]
        ],
        'scenes': [
            {
                'idx': s.get('idx'),
                'beat': s.get('beat'),
                'visual_concept': s.get('visual_concept'),
                'is_hero': s.get('is_hero'),
            }
            for s in scenes[:80]
        ],
        'music_plan': {
            'library_asset_id': music_plan.get('library_asset_id'),
            'gain_db': music_plan.get('gain_db'),
        },
    }


def _clipping_context_payload(
    ctx: StageContext,
    candidates: list['ClipCandidate'],
) -> dict[str, Any]:
    """Compact clipping facts for the agent user prompt."""
    return {
        'topic': ctx.run.topic,
        'candidates': [
            {
                'title': c.title,
                'start_sec': c.start_sec,
                'end_sec': c.end_sec,
                'hook_text': c.hook_text,
                'arrangement': getattr(c, 'arrangement', '') or 'contiguous',
                'beats': getattr(c, 'beats', None) or [],
                'virality_score': c.virality_score,
                'hook_score': c.hook_score,
                'flow_score': getattr(c, 'flow_score', 0.0),
                'value_score': getattr(c, 'value_score', 0.0),
                'reason': getattr(c, 'reason', '') or '',
                'hook_reason': getattr(c, 'hook_reason', '') or '',
                'value_reason': getattr(c, 'value_reason', '') or '',
                'transcript_excerpt': (
                    (getattr(c, 'transcript_excerpt', '') or '')[:400]
                ),
            }
            for c in candidates[:40]
        ],
    }


@lru_cache(maxsize=4)
def _agent(model: str) -> Agent[StageContext, EditorBriefOutput]:
    """Create and cache the editor-brief agent on first call."""
    a: Agent[StageContext, EditorBriefOutput] = Agent(
        model,
        output_type=EditorBriefOutput,
        deps_type=StageContext,
    )

    @a.system_prompt
    async def _sys(ctx: RunContext[StageContext]) -> str:  # pragma: no cover
        variables = {'topic': ctx.deps.run.topic}
        sys, _ = await ctx.deps.prompts.render('editor_brief', variables)
        return sys or (
            'You write handoff briefs for professional video editors '
            'working in DaVinci Resolve. Be concrete and actionable. '
            'Do not invent timestamps. VO/narration is the master clock '
            'for longform; clipping editors already have the source video. '
            'Fill every field with useful guidance for a seamless edit.'
        )

    return a


async def _run_editorial_agent(
    ctx: StageContext,
    *,
    clipping: bool,
    candidates: list['ClipCandidate'],
) -> EditorBriefOutput:
    """Call the LLM for editorial front matter."""
    payload = (
        _clipping_context_payload(ctx, candidates)
        if clipping
        else _longform_context_payload(ctx)
    )
    kind = 'clipping' if clipping else 'longform'
    facts_json = json.dumps(payload, default=str)[:_MAX_PROMPT_CHARS]
    variables = {
        'topic': ctx.run.topic,
        'kind': kind,
        'facts_json': facts_json,
    }
    _, usr = await ctx.prompts.render('editor_brief', variables)
    user_prompt = usr or (
        f'Write an editor handoff brief for this {kind} package.\n'
        f'Topic: {ctx.run.topic}\n'
        f'Facts (JSON):\n{facts_json}\n'
        'Return structured editorial guidance for Resolve.'
    )
    model_slug = await resolve_stage_model(ctx, 'editor_brief')
    return await llm_client.run_agent(
        _agent(to_pydantic_ai_model(model_slug)),
        user_prompt,
        ctx,
        stage_key='editor_brief',
        model_slug=model_slug,
    )


@register_stage
class EditorBriefStage(Stage):
    """Handoff stage: LLM editorial brief + deterministic appendix."""

    key = 'editor_brief'
    queue = 'api'
    max_retries = 3
    timeout_s = 180

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Build and save EDIT_BRIEF.md; return its asset id and run kind."""
        from server.apps.assets.models import AssetKind  # noqa: PLC0415

        clipping = is_clipping_run(ctx.upstream)
        candidates = await _load_approved_candidates(ctx) if clipping else []
        editorial = await _run_editorial_agent(
            ctx,
            clipping=clipping,
            candidates=candidates,
        )
        front = _render_editorial_markdown(str(ctx.run.topic), editorial)
        appendix = (
            await _build_clipping_appendix(ctx)
            if clipping
            else _build_longform_appendix(ctx)
        )
        markdown = f'{front}\n---\n\n{appendix}'
        assert markdown.strip(), (  # noqa: S101
            'EDIT_BRIEF.md content must not be empty'
        )

        asset = await ctx.assets.save(
            kind=AssetKind.DOC,
            content=markdown.encode(),
            filename='EDIT_BRIEF.md',
            mime='text/markdown',
        )
        return {
            'brief_asset_id': str(asset.id),
            'kind': 'clipping' if clipping else 'longform',
            'editorial': editorial.model_dump(),
        }
