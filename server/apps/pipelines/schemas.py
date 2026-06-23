"""Pydantic output schemas for all generation stage types.

These are BaseModel subclasses (not msgspec.Struct) because PydanticAI
requires output_type to be a pydantic BaseModel for structured extraction.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class ResearchSource(BaseModel):
    """A single web source found during research."""

    url: str
    title: str
    key_facts: list[str]


class ResearchBrief(BaseModel):
    """Synthesised research brief for the topic."""

    topic: str
    key_facts: list[str]
    sources: list[ResearchSource]
    narrative_angles: list[str]
    hooks: list[str]


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


class ScriptChapter(BaseModel):
    """Narration script for one chapter."""

    idx: int
    title: str
    text: str
    word_count: int = Field(ge=1)
    closing_line: str


class ScriptOutput(BaseModel):
    """Full output of the script stage."""

    chapters: list[ScriptChapter]
    total_word_count: int = Field(ge=1)


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


class SceneBreakdownOutput(BaseModel):
    """Full output of the scene_breakdown stage."""

    scenes: list[Scene]

    @model_validator(mode='after')
    def enforce_invariants(self) -> SceneBreakdownOutput:
        """Validate per-scene word count and cast limits."""
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
    gain_db: float = 0.0


class MusicPlanOutput(BaseModel):
    """Full output of the music_plan stage."""

    entries: list[MusicEntry]


class VideoMetadata(BaseModel):
    """YouTube metadata output from the metadata stage."""

    title: str = Field(max_length=60)
    description: str
    tags: list[str] = Field(default_factory=list)
    category: str = 'Education'
