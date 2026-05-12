from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel
from pydantic import Field


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
    scene_index: int = 0
    section: str = "SECTION_1"
    description: str = ""
    subject: str = ""
    setting: str = ""
    lighting: str = ""
    camera_angle: str = "eye-level"
    colour_palette: list[str] = []
    style_preset: str = "cinematic_realism"
    stock_search_keywords: list[str] = []
    duration_seconds: int = 8
    visual_type: str = ""
    mood: str = ""
    fallback_description: str = ""


class ScriptSection(BaseModel):
    tag: str
    content: str = ""
    word_count: int = 0
    estimated_duration_seconds: int = 0
    narrator_pacing: NarratorPacing = NarratorPacing.NORMAL
    narrator_notes: str = ""
    broll_indices: list[int] = []


class ScriptChapter(BaseModel):
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
    url: str = ""
    title: str = ""
    key_claim: str = ""


class ScriptQualityFlags(BaseModel):
    hook_score: float = 0.0
    hook_type: str = ""
    avg_sentence_length: float = 0.0
    passive_voice_instances: int = 0
    jargon_flags: list[str] = []
    faceless_compliance: bool = False
    research_confidence: str = "LOW"
    open_loops_resolved: bool = False


class ScriptAgentOutput(BaseModel):
    script_text: str = ""
    sections: list[ScriptSection] = []
    hook_used: str = ""
    hook_score: float = 0.0
    word_count: int = 0
    estimated_duration_mins: float = 0.0
    broll_suggestions: list[AgentBRollSuggestion] = []
    research_sources: list[ResearchSource] = []
    seo_metadata: ScriptSEOMetadata = ScriptSEOMetadata()
    quality_flags: ScriptQualityFlags = ScriptQualityFlags()
    ready_for_production: bool = False
    revision_notes: str = ""
    narrative_mode: str = Field(default="")
    open_loops_planted: int = Field(default=0)
    aha_moments_count: int = Field(default=0)
