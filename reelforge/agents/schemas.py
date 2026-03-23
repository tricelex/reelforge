from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

# ── Provider output dataclasses (transient — never stored directly) ───────────


@dataclass
class VideoResult:
    title: str
    url: str
    channel: str
    channel_id: str
    channel_handle: str
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


class ScriptSectionTag(StrEnum):
    HOOK = "HOOK"
    INTRO_BRIDGE = "INTRO_BRIDGE"
    SECTION_1 = "SECTION_1"
    SECTION_2 = "SECTION_2"
    SECTION_3 = "SECTION_3"
    TAKEAWAY = "TAKEAWAY"
    OUTRO_CTA = "OUTRO_CTA"


class NarratorPacing(StrEnum):
    SLOW = "SLOW"
    NORMAL = "NORMAL"
    FAST = "FAST"
    WHISPER = "WHISPER"


class AgentBRollSuggestion(BaseModel):
    """Structured B-roll cue as returned by the ScriptAgent."""

    scene_index: int = 0
    section: str = "SECTION_1"
    description: str = ""
    subject: str = ""  # main subject of the image
    setting: str = ""  # where the scene takes place
    lighting: str = ""  # lighting style (e.g. "soft natural light", "dramatic rim lighting")
    camera_angle: str = "eye-level"  # eye-level | bird's eye | low angle | dutch angle
    colour_palette: list[str] = []  # hex codes or descriptive colour names
    style_preset: str = "cinematic_realism"  # cinematic_realism | flat_illustration | dark_tech | corporate_clean
    stock_search_keywords: list[str] = []
    duration_seconds: int = 8
    visual_type: str = ""
    mood: str = ""
    fallback_description: str = ""


class ScriptSection(BaseModel):
    """A single script section with narration and b-roll metadata."""

    tag: str
    content: str = ""
    word_count: int = 0
    estimated_duration_seconds: int = 0
    narrator_pacing: NarratorPacing = NarratorPacing.NORMAL
    narrator_notes: str = ""
    broll_indices: list[int] = []


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
    thumbnail_text: str = ""
    thumbnail_emotion: str = ""
    search_hashtags: list[str] = []


class ResearchSource(BaseModel):
    """A research source cited in the script."""

    url: str = ""
    title: str = ""
    key_claim: str = ""


class ScriptQualityFlags(BaseModel):
    """Agent self-assessment of script quality."""

    hook_score: float = 0.0
    hook_type: str = ""
    avg_sentence_length: float = 0.0
    passive_voice_instances: int = 0
    jargon_flags: list[str] = []
    faceless_compliance: bool = False
    research_confidence: str = "LOW"
    narrative_mode_selected: str = ""
    open_loops_resolved: bool = False


class ScriptAgentOutput(BaseModel):
    script_text: str = ""  # Full script with [SECTION] markers
    sections: list[ScriptSection] = []
    hook_used: str = ""  # Text of the winning hook
    hook_score: float = 0.0
    word_count: int = 0
    estimated_duration_mins: float = 0.0
    broll_suggestions: list[AgentBRollSuggestion] = []
    research_sources: list[ResearchSource] = []
    seo_metadata: ScriptSEOMetadata = ScriptSEOMetadata()
    quality_flags: ScriptQualityFlags = ScriptQualityFlags()
    ready_for_production: bool = False
    revision_notes: str = ""
    narrative_mode: str = Field(
        default="",
        description="The narrative mode selected: REVEAL | CHRONICLE | TRANSFORMATION | VERDICT | STORY | EXPOSE | COUNTDOWN",
    )
    open_loops_planted: int = Field(default=0, description="Number of open loops planted and resolved in the script")
    aha_moments_count: int = Field(default=0, description="Number of genuine aha/revelation moments delivered")


# ── Visual Planner Agent Output ───────────────────────────────────────────────


class VisualSegment(BaseModel):
    """A single timed image segment in the visual timeline."""

    scene_id: int = Field(..., description="Sequential 1-based integer")
    section_tag: str = Field(..., description="The script [SECTION_TAG] this segment belongs to")
    start_seconds: float = Field(..., ge=0)
    end_seconds: float = Field(..., gt=0)
    duration: float = Field(..., gt=0, le=10)
    narration_excerpt: str
    image_prompt: str = Field(..., description="Minimum 40 words")
    style_preset: Literal["cinematic_realism", "flat_illustration", "dark_tech", "corporate_clean"]
    colour_palette: list[str] = Field(default_factory=list)
    animation_type: Literal[
        "hook", "intro", "body_concept", "body_stat", "body_story",
        "transition", "takeaway", "outro"
    ]
    video_prompt: str
    mood: Literal["calm", "tense", "inspiring", "curious", "urgent", "warm"]
    visual_keywords: list[str] = Field(default_factory=list)
    is_transition: bool = False

    @model_validator(mode="after")
    def check_duration_matches(self) -> VisualSegment:
        computed = round(self.end_seconds - self.start_seconds, 3)
        if abs(computed - self.duration) > 0.1:
            raise ValueError(
                f"duration {self.duration} does not match end_seconds - start_seconds = {computed}"
            )
        return self


class VisualPlannerOutput(BaseModel):
    """Full output of the VisualPlannerAgent."""

    segments: list[VisualSegment] = Field(..., min_length=10)
    total_duration_seconds: float
    segment_count: int
    coverage_confirmed: bool
    revision_notes: str = ""

    @model_validator(mode="after")
    def check_coverage(self) -> VisualPlannerOutput:
        if self.segment_count != len(self.segments):
            raise ValueError(
                f"segment_count={self.segment_count} does not match len(segments)={len(self.segments)}"
            )
        # segments is guaranteed non-empty by Field(min_length=10) — guard kept for safety
        segs = sorted(self.segments, key=lambda s: s.start_seconds)
        for i in range(1, len(segs)):
            gap = segs[i].start_seconds - segs[i - 1].end_seconds
            if abs(gap) > 0.1:
                raise ValueError(
                    f"Gap of {gap:.2f}s between segment {i} and {i+1}"
                )
        if abs(segs[-1].end_seconds - self.total_duration_seconds) > 0.5:
            raise ValueError(
                f"Timeline ends at {segs[-1].end_seconds:.2f}s "
                f"but total_duration is {self.total_duration_seconds:.2f}s"
            )
        return self
