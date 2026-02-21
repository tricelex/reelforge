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
    """A single B-roll cue for image generation."""

    timestamp_approx: int = 0  # seconds from start
    description: str = ""


class BRollSuggestions(RootModel[list[BRollSuggestion]]):
    """B-roll cues consumed by AssetJob for image generation."""

    root: list[BRollSuggestion] = []


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
