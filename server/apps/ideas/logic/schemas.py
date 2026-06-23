"""Pydantic schemas for ideation LLM structured output."""

import pydantic


class SourceRef(pydantic.BaseModel):
    """Provenance link for a remix or inspiration source."""

    url: str
    title: str = ''
    video_id: str = ''


class TopicCandidate(pydantic.BaseModel):
    """One scored topic proposal from the ideation agent."""

    title: str
    topic: str
    score: float
    remix_strategy: str
    hook_pattern: str
    differentiation: str
    source_refs: list[SourceRef] = pydantic.Field(default_factory=list)


class IdeationOutput(pydantic.BaseModel):
    """Structured output from the ideation agent."""

    ideas: list[TopicCandidate]


class SourceSnapshot(pydantic.BaseModel):
    """Ingested YouTube source material for remix ideation."""

    url: str
    video_id: str
    title: str
    description: str
    channel: str
    duration_sec: float
    view_count: int | None
    caption_text: str
