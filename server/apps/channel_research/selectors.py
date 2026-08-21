"""Read-only query helpers for channel research jobs."""

import base64
import uuid
from datetime import datetime

import msgspec
from django.db.models import Q, QuerySet

from server.apps.channel_research.logic.value_objects import (
    ChannelResearchJobPayload,
    ChannelResearchListPayload,
    ChannelSpecPayload,
    ResearchReportPayload,
    ToolTraceEntryPayload,
    UsagePayload,
)
from server.apps.channel_research.models import ChannelResearchJob

_MAX_PAGE_SIZE = 50


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _as_spec(raw: object) -> ChannelSpecPayload | None:
    if not isinstance(raw, dict) or not raw:
        return None
    return msgspec.convert(raw, type=ChannelSpecPayload)


def _as_report(raw: object) -> ResearchReportPayload | None:
    if not isinstance(raw, dict) or not raw:
        return None
    return msgspec.convert(raw, type=ResearchReportPayload)


def _as_trace(raw: object) -> list[ToolTraceEntryPayload]:
    if not isinstance(raw, list):
        return []
    return msgspec.convert(raw, type=list[ToolTraceEntryPayload])


def _as_usage(raw: object) -> UsagePayload:
    if not isinstance(raw, dict):
        return UsagePayload()
    return msgspec.convert(raw, type=UsagePayload)


def job_to_payload(job: ChannelResearchJob) -> ChannelResearchJobPayload:
    """Map a ChannelResearchJob row to its API payload."""
    created_by_id = str(job.created_by_id) if job.created_by_id else None
    return ChannelResearchJobPayload(
        id=str(job.id),
        source_channel_url=job.source_channel_url,
        target_market=job.target_market,
        working_name=job.working_name,
        kind=job.kind,  # type: ignore[arg-type]
        notes=job.notes,
        source_channel_id=job.source_channel_id,
        source_channel_name=job.source_channel_name,
        status=job.status,  # type: ignore[arg-type]
        research_report=_as_report(job.research_report),
        channel_spec=_as_spec(job.channel_spec),
        tool_trace=_as_trace(job.tool_trace),
        usage=_as_usage(job.usage),
        error_message=job.error_message,
        created_by_id=created_by_id,
        created_at=_iso(job.created_at),
        updated_at=_iso(job.updated_at),
    )


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    ts_str, job_id_str = raw.split('|', maxsplit=1)
    return datetime.fromisoformat(ts_str), uuid.UUID(job_id_str)


def _encode_cursor(job: ChannelResearchJob) -> str:
    raw = f'{job.created_at.isoformat()}|{job.id}'
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _apply_filters(
    qs: QuerySet[ChannelResearchJob],
    *,
    status: str | None,
) -> QuerySet[ChannelResearchJob]:
    if status:
        qs = qs.filter(status=status)
    return qs


def list_jobs(
    *,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> ChannelResearchListPayload:
    """Return a cursor-paginated job list."""
    page_size = min(max(limit, 1), _MAX_PAGE_SIZE)
    qs = ChannelResearchJob.objects.order_by('-created_at', '-id')
    qs = _apply_filters(qs, status=status)
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
    return ChannelResearchListPayload(
        items=[job_to_payload(row) for row in items],
        next_cursor=next_cursor,
        total=total,
    )


def get_job(job_id: str) -> ChannelResearchJobPayload:
    """Return one research job."""
    job = ChannelResearchJob.objects.get(id=uuid.UUID(job_id))
    return job_to_payload(job)
