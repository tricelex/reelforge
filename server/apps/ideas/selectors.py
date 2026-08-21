"""Read-only query helpers for topic ideas."""

import base64
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.db.models import Q, QuerySet

from server.apps.ideas.logic.constants import IdeaStatus
from server.apps.ideas.logic.value_objects import (
    IdeaListPayload,
    TopicIdeaPayload,
)

if TYPE_CHECKING:
    from server.apps.channels.models import NicheConfig
    from server.apps.ideas.models import TopicIdea

_MAX_PAGE_SIZE = 50


@dataclass(frozen=True, slots=True)
class IdeationContext:
    """Pre-fetched niche context injected into the ideation agent prompt."""

    audience: str
    angle: str
    lore_document: str
    banned_topics: list[str]
    format_name: str
    existing_topics: set[str]
    performance_notes: str = ''
    visual_medium: str = ''


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _idea_to_payload(idea: 'TopicIdea') -> TopicIdeaPayload:
    metadata: dict[str, Any] = idea.metadata or {}
    return TopicIdeaPayload(
        id=str(idea.id),
        channel_id=str(idea.channel_id),
        niche_id=str(idea.niche_id) if idea.niche_id else None,
        title=idea.title,
        topic=idea.topic,
        score=idea.score,
        status=idea.status,
        run_id=str(idea.run_id) if idea.run_id else None,
        rejection_reason=idea.rejection_reason,
        metadata=metadata,
        created_at=_iso(idea.created_at),
    )


def existing_topics(channel_id: uuid.UUID) -> set[str]:
    """Return normalized topics already used by runs and non-rejected ideas."""
    from server.apps.ideas.models import TopicIdea  # noqa: PLC0415
    from server.apps.pipelines.models import PipelineRun  # noqa: PLC0415

    run_topics = (
        PipelineRun.objects
        .filter(channel_id=channel_id)
        .order_by('-created_at')
        .values_list('topic', flat=True)[:30]
    )
    idea_topics = (
        TopicIdea.objects
        .filter(channel_id=channel_id)
        .exclude(status=IdeaStatus.REJECTED)
        .values_list('topic', flat=True)[:50]
    )
    return {value.lower().strip() for value in (*run_topics, *idea_topics)}


def _performance_notes(channel_id: uuid.UUID) -> str:
    """Summarize trailing average-view-percentage across the channel's runs."""
    from server.apps.analytics.models import PublishJobMetric  # noqa: PLC0415

    values = list(
        PublishJobMetric.objects
        .filter(
            publish_job__channel_id=channel_id,
        )
        .order_by('-pulled_at')
        .values_list('avg_view_percentage', flat=True)[:20],
    )
    if not values:
        return ''
    avg = sum(values) / len(values)
    return (
        f"This channel's last {len(values)} tracked videos averaged "
        f'{avg:.1f}% average-view-percentage.'
    )


def build_ideation_context(niche: 'NicheConfig') -> IdeationContext:
    """Build the pre-fetch bundle for one niche ideation call."""
    story_format = niche.format
    format_name = story_format.name if story_format is not None else ''
    return IdeationContext(
        audience=niche.audience,
        angle=niche.angle,
        lore_document=niche.lore_document,
        banned_topics=list(niche.banned_topics),
        format_name=format_name,
        existing_topics=existing_topics(niche.channel_id),
        performance_notes=_performance_notes(niche.channel_id),
        visual_medium=niche.visual_medium,
    )


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    ts_str, idea_id_str = raw.split('|', maxsplit=1)
    return datetime.fromisoformat(ts_str), uuid.UUID(idea_id_str)


def _encode_cursor(idea: 'TopicIdea') -> str:
    raw = f'{idea.created_at.isoformat()}|{idea.id}'
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _apply_filters(
    qs: QuerySet['TopicIdea'],
    *,
    status: str | None,
    channel_id: str | None,
    niche_id: str | None,
) -> QuerySet['TopicIdea']:
    if status:
        qs = qs.filter(status=status)
    if channel_id:
        qs = qs.filter(channel_id=uuid.UUID(channel_id))
    if niche_id:
        qs = qs.filter(niche_id=uuid.UUID(niche_id))
    return qs


def list_ideas(
    *,
    status: str | None = None,
    channel_id: str | None = None,
    niche_id: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> IdeaListPayload:
    """Return a cursor-paginated backlog list."""
    from server.apps.ideas.models import TopicIdea  # noqa: PLC0415

    page_size = min(max(limit, 1), _MAX_PAGE_SIZE)
    qs = TopicIdea.objects.order_by('-created_at', '-id')
    qs = _apply_filters(
        qs,
        status=status,
        channel_id=channel_id,
        niche_id=niche_id,
    )
    total = qs.count()

    if cursor:
        cursor_dt, cursor_id = _decode_cursor(cursor)
        qs = qs.filter(
            Q(created_at__lt=cursor_dt)
            | Q(created_at=cursor_dt, id__lt=cursor_id),
        )

    rows = list(qs[: page_size + 1])
    has_more = len(rows) > page_size
    items = rows[:page_size]
    next_cursor = _encode_cursor(items[-1]) if has_more and items else None

    return IdeaListPayload(
        items=[_idea_to_payload(row) for row in items],
        next_cursor=next_cursor,
        total=total,
    )


def get_idea(idea_id: str) -> TopicIdeaPayload:
    """Return one topic idea."""
    from server.apps.ideas.models import TopicIdea  # noqa: PLC0415

    idea = TopicIdea.objects.get(id=uuid.UUID(idea_id))
    return _idea_to_payload(idea)
