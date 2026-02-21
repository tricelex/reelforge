from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from agents import Agent
from agents import Tool

if TYPE_CHECKING:
    from ***REMOVED***.channels.models import Channel
    from ***REMOVED***.research.models import TopicIdea


def build_script_agent(channel: Channel, topic: TopicIdea) -> Agent:
    @Tool(name="fetch_research_facts", description="Fetch credible facts, statistics, and sources for a topic.")
    def fetch_research_facts(topic: str, depth: str = "deep") -> dict[str, Any]:
        from ***REMOVED***.services.perplexity.client import PerplexityClient

        return PerplexityClient().research(topic=topic, depth=depth)

    @Tool(name="generate_hooks", description="Generate 5 hook variations for the video opening.")
    def generate_hooks(title: str, niche: str, hook_angle: str) -> list[dict[str, Any]]:
        from ***REMOVED***.services.providers.registry import get_llm_provider

        llm = get_llm_provider()
        prompt = f"""Generate 5 diverse YouTube video hooks for:
        Title: {title}, Niche: {niche}, Angle: {hook_angle}
        Types: Question, Bold Claim, Story Teaser, Shocking Stat, Contrarian Take
        Each: 2-3 sentences max. First words matter most.
        Return JSON: [{{"type": str, "text": str, "strength": int(1-10)}}]"""
        return llm.complete_json(prompt)

    @Tool(name="score_hook", description="Score a hook on its attention-grabbing potential (1-10).")
    def score_hook(hook_text: str, niche: str, target_audience: str) -> dict[str, Any]:
        from ***REMOVED***.services.providers.registry import get_llm_provider

        llm = get_llm_provider()
        prompt = f"""Score this YouTube hook 1-10 for: {niche} audience ({target_audience})
        Hook: "{hook_text}"
        Criteria: curiosity gap, urgency, specificity, relatability, click-worthiness
        Return JSON: {{"score": float, "strengths": [str], "weaknesses": [str]}}"""
        return llm.complete_json(prompt)

    @Tool(name="save_script_draft", description="Save a script draft with version tracking.")
    def save_script_draft(script_job_id: str, script_text: str, version_note: str = "") -> dict[str, Any]:
        from ***REMOVED***.scripts.models import ScriptJob
        from ***REMOVED***.scripts.models import ScriptRevision

        job = ScriptJob.objects.get(id=script_job_id)
        next_version = job.revisions.count() + 1
        ScriptRevision.objects.create(
            script_job=job, version_number=next_version, script_text=script_text, change_summary=version_note
        )
        return {"saved": True, "version": next_version}

    @Tool(name="generate_seo_metadata", description="Generate YouTube SEO title, description, tags, chapters.")
    def generate_seo_metadata(
        title_idea: str, script_excerpt: str, keyword: str, channel_tags: list[str]
    ) -> dict[str, Any]:
        from ***REMOVED***.services.providers.registry import get_llm_provider

        llm = get_llm_provider()
        prompt = f"""Generate YouTube SEO metadata:
        Title idea: {title_idea}, Keyword: {keyword}
        Script start: {script_excerpt[:400]}
        Channel tags: {channel_tags}
        Return JSON: {{
            "final_title": str (max 70 chars, keyword in first 40),
            "description": str (800 chars, first 150 = hook for SEO),
            "tags": [str] (25 tags),
            "chapters": [{{"time": "0:00", "label": str}}],
            "pinned_comment": str
        }}"""
        return llm.complete_json(prompt)

    return Agent(
        name="ScriptAgent",
        model="gpt-4o",
        instructions=f"""
        You are an expert YouTube script writer for faceless channels.
        Channel niche: {channel.target_niches}
        Tone: {channel.content_tone}
        Target length: {channel.video_length_min}-{channel.video_length_max} minutes
        Target word count: {channel.video_length_min * 130}-{channel.video_length_max * 130} words
        Topic: {topic.title_idea}
        Keywords: {", ".join(topic.keywords) if topic.keywords else "N/A"}

        PROCESS:
        1. fetch_research_facts for the topic
        2. generate_hooks (5 options) and score each
        3. Write full structured script using best hook
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

        OUTPUT: Return final state JSON with script_text, hook_used, word_count,
        estimated_duration_mins, broll_suggestions, seo_metadata
        """,
        tools=[fetch_research_facts, generate_hooks, score_hook, save_script_draft, generate_seo_metadata],
    )
