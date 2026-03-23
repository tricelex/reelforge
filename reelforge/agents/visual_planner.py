from __future__ import annotations

from agents import Agent

from ***REMOVED***.agents.schemas import VisualPlannerOutput
from ***REMOVED***.agents.visual_planner_prompt import VISUAL_PLANNER_INSTRUCTIONS


def build_visual_planner_agent(
    sections: list[dict],
    broll_suggestions: list[dict],
    total_duration_seconds: float,
    channel_tone: str = "informative",
    narrative_mode: str = "REVEAL",
) -> Agent:
    """Build the VisualPlannerAgent for a single script.

    Args:
        sections: ScriptAgent sections output — list of dicts with keys:
                    tag, content, estimated_duration_seconds
        broll_suggestions: ScriptAgent broll_suggestions — style anchors per section
        total_duration_seconds: Total audio duration from script estimate
        channel_tone: From channel.content_tone
        narrative_mode: The mode selected by ScriptAgent
    """
    # 1. Distribute total_duration_seconds proportionally by section weight
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
    # Fix floating-point drift on last section
    if section_timing:
        section_timing[-1]["end_seconds"] = total_duration_seconds
        section_timing[-1]["duration_seconds"] = round(
            total_duration_seconds - section_timing[-1]["start_seconds"], 2
        )

    # 2. Build b-roll style map (tag → broll dict)
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

    # 3. Compute segment targets per section (target 6s per segment)
    _TARGET_SEG_DURATION = 6.0
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

    # 4. Build section context block for prompt
    total_segments_needed = sum(t["n_segments"] for t in segment_targets)
    section_context_lines = []
    for t in segment_targets:
        content_preview = t["content"][:300]
        if len(t["content"]) > 300:
            content_preview += "..."
        section_context_lines.append(
            f"SECTION: [{t['tag']}]\n"
            f"  Time window    : {t['start_seconds']}s \u2192 {t['end_seconds']}s ({t['duration_seconds']}s)\n"
            f"  Segments needed: {t['n_segments']} segments \u00d7 ~{t['target_seg_duration']}s each\n"
            f"  Narration text : {content_preview}\n"
            f"  Style preset   : {t['style_preset']}\n"
            f"  Colour palette : {', '.join(t['colour_palette'])}\n"
            f"  Mood           : {t['mood']}\n"
            f"  Style anchor   : {t['style_description']}\n"
            f"  Subject anchor : {t['style_subject']}\n"
            f"  Lighting anchor: {t['style_lighting']}"
        )
    section_context = "\n\n".join(section_context_lines)

    return Agent(
        name="VisualPlannerAgent",
        model="gpt-5.2",
        output_type=VisualPlannerOutput,
        instructions=VISUAL_PLANNER_INSTRUCTIONS.format(
            narrative_mode=narrative_mode,
            channel_tone=channel_tone,
            total_duration_seconds=total_duration_seconds,
            total_sections=len(sections),
            total_segments_needed=total_segments_needed,
            section_context=section_context,
        ),
        tools=[],
    )
