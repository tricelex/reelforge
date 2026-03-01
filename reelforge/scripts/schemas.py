from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import RootModel


class ResearchData(BaseModel):
    """Facts, stats and sources gathered during script research phase."""

    facts: list[str] = []
    statistics: list[dict[str, Any]] = []
    sources: list[str] = []
    summary: str = ""


class Hook(BaseModel):
    """A single hook variation generated for the video opening."""

    text: str = ""
    type: Literal["question", "statement", "story", "stat", "contrarian"] = "statement"
    score: float = 0.0  # 1-10


class GeneratedHooks(RootModel[list[Hook]]):
    """Agent-generated hook variations for the video opening."""

    root: list[Hook] = []


class QAIssue(BaseModel):
    """A single QA issue found in the script."""

    issue: str = ""
    location: str = ""
    severity: Literal["low", "medium", "high"] = "low"


class QAIssueList(RootModel[list[QAIssue]]):
    """List of QA issues found or fixed in the script."""

    root: list[QAIssue] = []


class Chapter(BaseModel):
    """A YouTube chapter marker."""

    timestamp: str = "0:00"  # YouTube chapter format "M:SS"
    title: str = ""


class ChapterList(RootModel[list[Chapter]]):
    """YouTube chapter markers for the video."""

    root: list[Chapter] = []


class BRollSuggestion(BaseModel):
    """A single B-roll cue for image generation (stored format for AssetJob consumption)."""

    scene_index: int = 0
    section: str = ""
    description: str = ""
    stock_search_keywords: list[str] = []
    duration_seconds: int = 8
    visual_type: str = ""
    mood: str = ""
    fallback_description: str = ""


class BRollSuggestions(RootModel[list[BRollSuggestion]]):
    """B-roll cues consumed by AssetJob for image generation."""

    root: list[BRollSuggestion] = []


class ScriptSectionItem(BaseModel):
    """Stored script section (mirrors AgentScriptSection but uses plain strings for DB)."""

    tag: str = ""
    content: str = ""
    word_count: int = 0
    estimated_duration_seconds: int = 0
    narrator_pacing: str = "NORMAL"
    narrator_notes: str = ""
    broll_indices: list[int] = []


class ScriptSectionList(RootModel[list[ScriptSectionItem]]):
    """Parsed script sections stored on ScriptJob."""

    root: list[ScriptSectionItem] = []


class ScriptQualityFlagsSchema(BaseModel):
    """Agent quality self-assessment stored on ScriptJob."""

    hook_score: float = 0.0
    hook_type: str = ""
    avg_sentence_length: float = 0.0
    passive_voice_instances: int = 0
    jargon_flags: list[str] = []
    faceless_compliance: bool = False
    research_confidence: str = "LOW"


class ResearchSourceItem(BaseModel):
    """A single research source stored on ScriptJob."""

    url: str = ""
    title: str = ""
    key_claim: str = ""


class ResearchSourceList(RootModel[list[ResearchSourceItem]]):
    """Research sources stored on ScriptJob."""

    root: list[ResearchSourceItem] = []


class Segment(BaseModel):
    """A pre-chunked TTS segment driving VoiceoverSegment creation."""

    segment_id: int = 0
    text: str = ""
    section: str = ""  # "intro" | "body" | "conclusion"
    approx_start_sec: float = 0.0
    approx_end_sec: float = 0.0


class SegmentList(RootModel[list[Segment]]):
    """Pre-chunked TTS segments driving VoiceoverSegment creation."""

    root: list[Segment] = []
