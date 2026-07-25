"""Pydantic output schemas for all generation stage types.

These are BaseModel subclasses (not msgspec.Struct) because PydanticAI
requires output_type to be a pydantic BaseModel for structured extraction.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ResearchSource(BaseModel):
    """A single web source found during research."""

    url: str
    title: str
    key_facts: list[str]


_MIN_CORROBORATING_SOURCES = 2
_OVERLAP_THRESHOLD = 0.4


def _corroboration_count(fact: str, sources: list[ResearchSource]) -> int:
    """Count distinct sources whose key_facts overlap this brief-level fact."""
    fact_words = set(fact.lower().split())
    count = 0
    for source in sources:
        for source_fact in source.key_facts:
            source_words = set(source_fact.lower().split())
            if not fact_words or not source_words:
                continue
            overlap = len(fact_words & source_words) / len(fact_words)
            if overlap >= _OVERLAP_THRESHOLD:
                count += 1
                break
    return count


class ResearchBrief(BaseModel):
    """Synthesised research brief for the topic."""

    topic: str
    key_facts: list[str]
    sources: list[ResearchSource]
    narrative_angles: list[str]
    hooks: list[str]

    @model_validator(mode='after')
    def enforce_corroboration(self) -> ResearchBrief:
        """At least half of key_facts must have >=2 corroborating sources."""
        if not self.key_facts:
            return self
        corroborated = sum(
            1
            for fact in self.key_facts
            if _corroboration_count(fact, self.sources)
            >= _MIN_CORROBORATING_SOURCES
        )
        if corroborated < len(self.key_facts) / 2:
            msg = (
                'at least half of key_facts must have 2+ corroborating '
                'sources (matching entries in sources[].key_facts)'
            )
            raise ValueError(msg)
        return self


class ResearchOutput(BaseModel):
    """Full output of the research stage."""

    brief: ResearchBrief
    sources: list[ResearchSource]


class Chapter(BaseModel):
    """A single chapter in the documentary outline."""

    idx: int
    title: str
    thesis: str
    target_seconds: int = Field(gt=0)
    device: str


class OutlineOutput(BaseModel):
    """Full output of the outline stage."""

    chapters: list[Chapter]
    total_target_seconds: int = Field(gt=0)
    format_key: str = ''


def _word_overlap_ratio(text_a: str, text_b: str) -> float:
    """Fraction of text_b words that also appear in text_a (lowercased)."""
    words_a = set(text_a.lower().split())
    words_b = text_b.lower().split()
    if not words_b:
        return 1.0
    overlap = sum(1 for w in words_b if w in words_a)
    return overlap / len(words_b)


class ScriptChapter(BaseModel):
    """Narration script for one chapter."""

    idx: int
    title: str
    text: str
    word_count: int = Field(ge=1)
    closing_line: str
    commentary: str = Field(min_length=1)


class ScriptOutput(BaseModel):
    """Full output of the script stage."""

    chapters: list[ScriptChapter]
    total_word_count: int = Field(ge=1)

    @model_validator(mode='after')
    def enforce_commentary_distinct(self) -> ScriptOutput:
        """Half the chapters must have commentary distinct from narration."""
        if not self.chapters:
            return self
        distinct_count = sum(
            1
            for ch in self.chapters
            if _word_overlap_ratio(ch.text, ch.commentary) < 0.8
        )
        if distinct_count < len(self.chapters) / 2:
            msg = (
                'commentary must read as genuine analysis distinct from '
                'narration in at least half the chapters'
            )
            raise ValueError(msg)
        return self


class Scene(BaseModel):
    """One visual scene within a chapter."""

    idx: int
    chapter_idx: int
    beat: str
    narration_text: str
    visual_concept: str
    shot_type: str
    est_seconds: float = Field(gt=0)
    is_hero: bool
    foreground_cast: list[str] = Field(default_factory=list)
    word_count: int = Field(ge=1)

    @model_validator(mode='after')
    def sync_word_count(self) -> Scene:
        """Derive word_count from narration — LLMs routinely miscount by 1."""
        counted = len(self.narration_text.split())
        if self.word_count != counted:
            self.word_count = counted
        return self


class CastMember(BaseModel):
    """A distinct character implied by the script / scene breakdown."""

    name: str
    role: str = ''
    importance: Literal['main', 'secondary', 'background'] = 'secondary'
    appearance_brief: str = ''


class SceneBreakdownOutput(BaseModel):
    """Full output of the scene_breakdown stage."""

    scenes: list[Scene]
    cast: list[CastMember] = Field(default_factory=list)

    @model_validator(mode='after')
    def enforce_invariants(self) -> SceneBreakdownOutput:
        """Validate per-scene word count range and cast limits."""
        for s in self.scenes:
            if not (10 <= s.word_count <= 35):
                raise ValueError(
                    f'scene {s.idx} word_count {s.word_count} outside [10,35]',
                )
            if len(s.foreground_cast) > 2:
                raise ValueError(
                    f'scene {s.idx} has {len(s.foreground_cast)} foreground '
                    f'characters (max 2)',
                )
        return self


class NarrativeQCOutput(BaseModel):
    """LLM-judge score for a script + scene breakdown, before render spend."""

    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)


class VisualPrompt(BaseModel):
    """An image generation prompt for one scene."""

    scene_idx: int
    prompt: str
    negative_prompt: str = ''
    safety_flagged: bool = False
    character_ref_id: str | None = None


class VisualPromptsOutput(BaseModel):
    """Full output of the visual_prompts stage."""

    prompts: list[VisualPrompt]


class MusicEntry(BaseModel):
    """Music track assignment for one chapter."""

    chapter_idx: int
    library_asset_id: str
    gain_db: float = -18.0


class MusicPlanOutput(BaseModel):
    """Full output of the music_plan stage."""

    entries: list[MusicEntry]


class VideoMetadata(BaseModel):
    """YouTube metadata output from the metadata stage."""

    title: str = Field(max_length=60)
    description: str
    tags: list[str] = Field(default_factory=list)
    category: str = 'Education'
