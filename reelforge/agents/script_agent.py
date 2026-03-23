from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agents import Agent
from agents import function_tool
from ***REMOVED***.agents.schemas import ScriptAgentOutput
from ***REMOVED***.agents.script_agent_prompt import SCRIPT_AGENT_INSTRUCTIONS

if TYPE_CHECKING:
    from ***REMOVED***.agents.providers.protocols import LLMProvider
    from ***REMOVED***.agents.providers.protocols import WebSearchProvider
    from ***REMOVED***.channels.models import Channel
    from ***REMOVED***.research.models import TopicIdea


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
        """Fetch credible facts, statistics, and sources for a topic via web-grounded search.

        Returns JSON with keys: query, answer, key_facts, statistics, expert_quotes,
        common_misconceptions, sources (list of {url, title}), confidence.
        Call this at least 3 times with different angle queries before writing the script.
        """
        result = web_search.research(topic=topic, depth=depth)
        return json.dumps(result, default=str)

    @function_tool
    def generate_seo_metadata(title_idea: str, script_excerpt: str, keyword: str, channel_tags: list[str]) -> str:
        """Generate YouTube SEO title, description, tags, chapter markers, and thumbnail metadata.

        Returns JSON with final_title, description, tags, chapters, pinned_comment,
        thumbnail_text, thumbnail_emotion, and search_hashtags.
        """
        prompt = f"""Generate YouTube SEO metadata:
Title idea: {title_idea}, Keyword: {keyword}
Script start: {script_excerpt[:400]}
Channel tags: {channel_tags}
Return JSON: {{
    "final_title": "str (max 70 chars, keyword in first 40 chars, creates curiosity)",
    "description": "str (800 chars, first 150 chars = complete compelling sentence with keyword)",
    "tags": ["str (25 tags — mix of broad, specific, and long-tail)"],
    "chapters": [{{"time": "0:00", "label": "str (concise chapter label)"}}],
    "pinned_comment": "str (open-ended question that triggers genuine viewer responses)",
    "thumbnail_text": "str (2-5 words that create curiosity without spoiling the hook)",
    "thumbnail_emotion": "str (one word only: shock|curiosity|urgency|disbelief|aspiration)",
    "search_hashtags": ["str (3-5 most-searched hashtags for video description footer)"]
}}"""
        return json.dumps(llm.complete_json(prompt), default=str)

    channel_niches_str = ", ".join(channel.target_niches) if channel.target_niches else "general"
    keywords_str = ", ".join(topic.keywords) if topic.keywords else "N/A"
    content_format = getattr(topic, "content_format", "explainer") or "explainer"
    topic_hook_angle = getattr(topic, "angle", "") or ""
    target_length_min = channel.video_length_min
    target_length_max = channel.video_length_max
    target_wc_min = target_length_min * 130
    target_wc_max = target_length_max * 130

    description_str = topic.description or "N/A"
    why_it_works_str = topic.why_it_works or ""
    thumbnail_concept_str = topic.thumbnail_concept or ""
    community_questions_str = (
        "\n".join(f"  - {q}" for q in topic.community_questions) if topic.community_questions else "  None captured"
    )
    suggested_sources_str = (
        "\n".join(f"  - {s}" for s in topic.suggested_sources) if topic.suggested_sources else "  None captured"
    )

    return Agent(
        name="ScriptAgent",
        model="gpt-5.2",
        instructions=SCRIPT_AGENT_INSTRUCTIONS.format(
            channel=channel,
            topic=topic,
            channel_niches_str=channel_niches_str,
            content_format=content_format,
            target_length_min=target_length_min,
            target_length_max=target_length_max,
            target_wc_min=target_wc_min,
            target_wc_max=target_wc_max,
            topic_hook_angle=topic_hook_angle,
            keywords_str=keywords_str,
            description_str=description_str,
            why_it_works_str=why_it_works_str,
            thumbnail_concept_str=thumbnail_concept_str,
            community_questions_str=community_questions_str,
            suggested_sources_str=suggested_sources_str,
        ),
        output_type=ScriptAgentOutput,
        tools=[fetch_research_facts, generate_seo_metadata],
    )
