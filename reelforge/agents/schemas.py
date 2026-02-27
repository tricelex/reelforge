from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Literal

from pydantic import BaseModel

# ── Provider output dataclasses (transient — never stored directly) ───────────


@dataclass
class VideoResult:
    title: str
    url: str
    channel: str
    channel_id: str
    views: int | None
    likes: int | None
    published_at: str | None
    duration_seconds: int | None


@dataclass
class TrendPoint:
    date: str
    value: int


@dataclass
class TrendData:
    keyword: str
    interest_score: int
    trend_direction: str
    interest_over_time: list[TrendPoint] = field(default_factory=list)
    related_queries: list[str] = field(default_factory=list)


@dataclass
class CommunityPost:
    title: str
    score: int
    num_comments: int
    url: str
    source: str  # e.g. "hackernews", "perplexity"


@dataclass
class RisingTopic:
    keyword: str
    growth_rate: str
    category: str
    description: str


# ── Pydantic models (agent/LLM output — validated before saving) ─────────────


class ResearchTopicIdea(BaseModel):
    title_idea: str
    hook_angle: str
    target_keyword: str
    estimated_search_vol: int
    competition_level: Literal["LOW", "MEDIUM", "HIGH"]
    opportunity_score: float
    trend_direction: Literal["RISING", "STABLE", "DECLINING"]
    thumbnail_concept: str
    why_it_works: str
    content_format: str  # "listicle"|"tutorial"|"comparison"|"explainer"|"case-study"|"myth-debunk"|"deep-dive"
    source_signals: list[
        str
    ] = []  # which steps/tools surfaced this topic, e.g. ["community_step3", "competitor_gap_step4"]


class DiscoveredCompetitor(BaseModel):
    youtube_channel_id: str
    channel_name: str
    channel_url: str
    subscriber_count: int = 0
    notes: str = ""


class ResearchAgentOutput(BaseModel):
    topics: list[ResearchTopicIdea]
    research_summary: str = ""
    discovered_competitors: list[DiscoveredCompetitor] = []
    data_gaps: list[str] = []  # tools that returned poor or empty data during this run


# ── Script Agent Output ───────────────────────────────────────────────────────


class ScriptChapter(BaseModel):
    """Chapter marker as returned by the ScriptAgent (maps to ChapterList schema on save)."""

    time: str = "0:00"
    label: str = ""


class ScriptSEOMetadata(BaseModel):
    final_title: str = ""
    description: str = ""
    tags: list[str] = []
    chapters: list[ScriptChapter] = []
    pinned_comment: str = ""


class ScriptAgentOutput(BaseModel):
    script_text: str = ""  # Full script with [SECTION] markers
    hook_used: str = ""  # Text of the winning hook
    word_count: int = 0
    estimated_duration_mins: float = 0.0
    broll_suggestions: list[str] = []  # Plain strings; converted to BRollSuggestion on save
    seo_metadata: ScriptSEOMetadata = ScriptSEOMetadata()
