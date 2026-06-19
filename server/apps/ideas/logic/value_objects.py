"""API DTOs for ideation."""

from typing import Any

import msgspec


class TopicIdeaPayload(msgspec.Struct, frozen=True):
    """Read representation of one topic idea."""

    id: str
    channel_id: str
    niche_id: str | None
    title: str
    topic: str
    score: float
    status: str
    run_id: str | None
    rejection_reason: str
    metadata: dict[str, Any]
    created_at: str


class TopicIdeaPatchPayload(msgspec.Struct, frozen=True):
    """Partial update for a backlog idea."""

    title: str | None = None
    topic: str | None = None
    score: float | None = None
    status: str | None = None
    rejection_reason: str | None = None


class IdeaGeneratePayload(msgspec.Struct, frozen=True):
    """Batch-generate ideas for a niche."""

    count: int = 5
    source_url: str | None = None


class IdeaListPayload(msgspec.Struct, frozen=True):
    """Cursor-paginated idea list."""

    items: list[TopicIdeaPayload]
    next_cursor: str | None
    total: int


class PromoteIdeaResultPayload(msgspec.Struct, frozen=True):
    """Result of promoting an idea into a pipeline run."""

    idea_id: str
    run_id: str
    status: str
