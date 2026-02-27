from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agents import Agent
from agents import function_tool
from reelforge.agents.schemas import ScriptAgentOutput

if TYPE_CHECKING:
    from reelforge.agents.providers.protocols import LLMProvider
    from reelforge.agents.providers.protocols import WebSearchProvider
    from reelforge.channels.models import Channel
    from reelforge.research.models import TopicIdea


def build_script_agent(
    channel: Channel,
    topic: TopicIdea,
    web_search: WebSearchProvider,
    llm: LLMProvider,
) -> Agent:
    """Build the ScriptAgent with injected providers.

    Researches facts, generates hooks, writes the full script,
    and produces SEO metadata for a single TopicIdea.
    """

    @function_tool
    def fetch_research_facts(topic: str, depth: str = "deep") -> str:
        """Fetch credible facts, statistics, and sources for a topic via web-grounded AI search.

        Returns JSON with keys: query, answer, sources (list of {url}), model, usage.
        """
        result = web_search.research(topic=topic, depth=depth)
        return json.dumps(result, default=str)

    @function_tool
    def generate_hooks(title: str, niche: str, hook_angle: str) -> str:
        """Generate 5 hook variations for the video opening.

        Returns JSON array of {type, text, strength (1-10)}.
        Types: Question, Bold Claim, Story Teaser, Shocking Stat, Contrarian Take.
        """
        prompt = f"""Generate 5 diverse YouTube video hooks for:
Title: {title}, Niche: {niche}, Angle: {hook_angle}
Types: Question, Bold Claim, Story Teaser, Shocking Stat, Contrarian Take
Each: 2-3 sentences max. First words matter most.
Return JSON array: [{{"type": "str", "text": "str", "strength": 1}}]"""
        return json.dumps(llm.complete_json(prompt), default=str)

    @function_tool
    def score_hook(hook_text: str, niche: str, target_audience: str) -> str:
        """Score a hook on its attention-grabbing potential (1-10).

        Returns JSON with score (float), strengths ([str]), weaknesses ([str]).
        Criteria: curiosity gap, urgency, specificity, relatability, click-worthiness.
        """
        prompt = f"""Score this YouTube hook 1-10 for: {niche} audience ({target_audience})
Hook: "{hook_text}"
Criteria: curiosity gap, urgency, specificity, relatability, click-worthiness
Return JSON: {{"score": 0.0, "strengths": ["str"], "weaknesses": ["str"]}}"""
        return json.dumps(llm.complete_json(prompt), default=str)

    @function_tool
    def save_script_draft(script_job_id: str, script_text: str, version_note: str = "") -> str:
        """Save a script draft with version tracking.

        Returns JSON with saved (bool) and version (int).
        """
        from reelforge.scripts.models import ScriptJob
        from reelforge.scripts.models import ScriptRevision

        job = ScriptJob.objects.get(id=script_job_id)
        next_version = job.revisions.count() + 1
        ScriptRevision.objects.create(
            script_job=job,
            version_number=next_version,
            script_text=script_text,
            change_summary=version_note,
        )
        return json.dumps({"saved": True, "version": next_version})

    @function_tool
    def generate_seo_metadata(title_idea: str, script_excerpt: str, keyword: str, channel_tags: list[str]) -> str:
        """Generate YouTube SEO title, description, tags, and chapter markers.

        Returns JSON with final_title, description, tags ([str]), chapters ([{time, label}]),
        and pinned_comment.
        """
        prompt = f"""Generate YouTube SEO metadata:
Title idea: {title_idea}, Keyword: {keyword}
Script start: {script_excerpt[:400]}
Channel tags: {channel_tags}
Return JSON: {{
    "final_title": "str (max 70 chars, keyword in first 40)",
    "description": "str (800 chars, first 150 = hook for SEO)",
    "tags": ["str (25 tags)"],
    "chapters": [{{"time": "0:00", "label": "str"}}],
    "pinned_comment": "str"
}}"""
        return json.dumps(llm.complete_json(prompt), default=str)

    channel_niches_str = ", ".join(channel.target_niches) if channel.target_niches else "general"
    keywords_str = ", ".join(topic.keywords) if topic.keywords else "N/A"

    return Agent(
        name="ScriptAgent",
        model="gpt-4o",
        instructions=f"""
        You are an expert YouTube script writer for faceless channels.
        Channel niche: {channel_niches_str}
        Tone: {channel.content_tone}
        Target length: {channel.video_length_min}-{channel.video_length_max} minutes
        Target word count: {channel.video_length_min * 130}-{channel.video_length_max * 130} words
        Topic: {topic.title_idea}
        Keywords: {keywords_str}

        PROCESS:
        1. fetch_research_facts for the topic
        2. generate_hooks (5 options) and score_hook on each
        3. Write full structured script using best hook (score >= 7)
        4. save_script_draft (version 1)
        5. Self-review: check pacing, sentence length, transitions
        6. If issues found: save_script_draft (version 2 with fixes)
        7. generate_seo_metadata

        SCRIPT STRUCTURE (required sections):
        [HOOK] → [INTRO_BRIDGE] → [SECTION_1] → [SECTION_2] → [SECTION_3] → [TAKEAWAY] → [OUTRO_CTA]

        QUALITY BAR:
        - Hook score must be >= 7. If not, try another hook type.
        - No sentences > 20 words (spoken word pacing)
        - Every claim backed by research data
        - Active voice, second person ("you"), zero jargon

        OUTPUT: Return a ScriptAgentOutput JSON with:
        - script_text: full script with literal section tags on their own lines:
          [HOOK], [INTRO_BRIDGE], [SECTION_1], [SECTION_2], [SECTION_3], [TAKEAWAY], [OUTRO_CTA]
        - hook_used: exact text of the selected hook (score >= 7)
        - word_count: total word count
        - estimated_duration_mins: based on 130 words/min
        - broll_suggestions: list of visual cue strings (one per key scene)
        - seo_metadata: {{final_title, description, tags, chapters, pinned_comment}}
        """,
        output_type=ScriptAgentOutput,
        tools=[fetch_research_facts, generate_hooks, score_hook, save_script_draft, generate_seo_metadata],
    )
