from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import Agent
from pydantic_ai import RunContext

from ***REMOVED***.ai.schemas.visual import VisualPlannerOutput

if TYPE_CHECKING:
    from ***REMOVED***.ai.deps import VisualPlannerDeps

_TARGET_SEG_DURATION = 6.0
_SECTION_CONTENT_PREVIEW_CHARS = 300

visual_planner_agent: Agent[VisualPlannerDeps, VisualPlannerOutput] = Agent(
    "openai:gpt-4o",
    output_type=VisualPlannerOutput,
    retries=2,
)


def _build_section_context(deps: VisualPlannerDeps) -> tuple[str, int]:
    """Compute per-section timing and segment targets; return context string and total segment count."""
    sections = deps.sections
    broll_suggestions = deps.broll_suggestions
    total_duration_seconds = deps.total_duration_seconds

    raw_durations = [float(s.get("estimated_duration_seconds", 8)) for s in sections]
    raw_total = sum(raw_durations)
    section_timing: list[dict] = []
    cursor = 0.0
    for i, section in enumerate(sections):
        weight = raw_durations[i] / raw_total if raw_total > 0 else 1 / len(sections)
        duration = round(weight * total_duration_seconds, 2)
        section_timing.append({
            "index": i,
            "tag": section.get("tag", f"SECTION_{i + 1}"),
            "content": section.get("content", ""),
            "start_seconds": round(cursor, 2),
            "end_seconds": round(cursor + duration, 2),
            "duration_seconds": round(duration, 2),
        })
        cursor += duration
    if section_timing:
        section_timing[-1]["end_seconds"] = total_duration_seconds
        section_timing[-1]["duration_seconds"] = round(
            total_duration_seconds - section_timing[-1]["start_seconds"], 2
        )

    broll_by_section: dict[str, dict] = {}
    for broll in broll_suggestions:
        section_key = broll.get("section", "")
        if section_key and section_key not in broll_by_section:
            broll_by_section[section_key] = broll
    for i, broll in enumerate(broll_suggestions):
        if i < len(section_timing):
            tag = section_timing[i]["tag"]
            if tag not in broll_by_section:
                broll_by_section[tag] = broll

    segment_targets: list[dict] = []
    for st in section_timing:
        n_segments = max(1, round(st["duration_seconds"] / _TARGET_SEG_DURATION))
        actual_seg_duration = round(st["duration_seconds"] / n_segments, 2)
        style = broll_by_section.get(st["tag"], {})
        segment_targets.append({
            **st,
            "n_segments": n_segments,
            "target_seg_duration": actual_seg_duration,
            "style_preset": style.get("style_preset", "cinematic_realism"),
            "colour_palette": style.get("colour_palette", ["#0A0A0A", "#FFFFFF"]),
            "mood": style.get("mood", "curious"),
            "style_description": style.get("description", ""),
            "style_subject": style.get("subject", ""),
            "style_lighting": style.get("lighting", "natural light"),
        })

    total_segments_needed = sum(t["n_segments"] for t in segment_targets)
    lines = []
    for t in segment_targets:
        content_preview = t["content"][:_SECTION_CONTENT_PREVIEW_CHARS]
        if len(t["content"]) > _SECTION_CONTENT_PREVIEW_CHARS:
            content_preview += "..."
        lines.append(
            f"SECTION: [{t['tag']}]\n"
            f"  Time window    : {t['start_seconds']}s → {t['end_seconds']}s ({t['duration_seconds']}s)\n"
            f"  Segments needed: {t['n_segments']} segments x ~{t['target_seg_duration']}s each\n"
            f"  Narration text : {content_preview}\n"
            f"  Style preset   : {t['style_preset']}\n"
            f"  Colour palette : {', '.join(t['colour_palette'])}\n"
            f"  Mood           : {t['mood']}\n"
            f"  Style anchor   : {t['style_description']}\n"
            f"  Subject anchor : {t['style_subject']}\n"
            f"  Lighting anchor: {t['style_lighting']}"
        )
    section_context = "\n\n".join(lines)
    section_context = section_context.replace("{", "{{").replace("}", "}}")
    return section_context, total_segments_needed


@visual_planner_agent.system_prompt
def _system_prompt(ctx: RunContext[VisualPlannerDeps]) -> str:
    from ***REMOVED***.ai.prompts.visual_planner import VISUAL_PLANNER_INSTRUCTIONS

    deps = ctx.deps
    section_context, total_segments_needed = _build_section_context(deps)

    return VISUAL_PLANNER_INSTRUCTIONS.format(
        narrative_mode=deps.narrative_mode,
        channel_tone=deps.channel_tone,
        total_duration_seconds=deps.total_duration_seconds,
        total_sections=len(deps.sections),
        total_segments_needed=total_segments_needed,
        section_context=section_context,
    )
