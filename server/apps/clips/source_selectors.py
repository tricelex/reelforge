"""Read-only query helpers for clip sources."""

import uuid

from django.db.models import Count

from server.apps.clips.logic.value_objects import (
    ClipSourceListPayload,
    ClipSourcePayload,
)
from server.apps.clips.models import ClipSource
from server.common.pagination import paginate_queryset


def _source_url(source: ClipSource) -> str:
    if source.url:
        return source.url
    if source.library_asset_id:
        return str(source.library_asset_id)
    return ''


def _to_payload(source: ClipSource, *, candidate_count: int) -> ClipSourcePayload:
    library_asset_id = (
        str(source.library_asset_id)
        if source.library_asset_id is not None
        else None
    )
    return ClipSourcePayload(
        id=str(source.id),
        channel_id=str(source.channel_id),
        run_id=str(source.run_id) if source.run_id else None,
        title=source.title,
        status=source.status,
        duration_sec=source.duration_sec,
        candidate_count=candidate_count,
        campaign_id=str(source.campaign_id) if source.campaign_id else None,
        source_type=source.source_type,
        url=_source_url(source),
        library_asset_id=library_asset_id,
        error_message=source.error_message or None,
    )


def _annotate_candidate_count(qs):  # type: ignore[no-untyped-def]
    return qs.annotate(
        candidate_count=Count(
            'run__clip_candidates',
            distinct=True,
        ),
    )


def list_clip_sources(
    *,
    channel_id: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> ClipSourceListPayload:
    """Return clip sources with optional filters."""
    qs = ClipSource.objects.order_by('-created_at', '-id')
    if channel_id:
        qs = qs.filter(channel_id=uuid.UUID(channel_id))
    if status:
        qs = qs.filter(status=status)
    qs = _annotate_candidate_count(qs)
    rows, next_cursor, total = paginate_queryset(
        qs,
        cursor=cursor,
        limit=limit,
    )
    return ClipSourceListPayload(
        items=[
            _to_payload(
                row,
                candidate_count=int(getattr(row, 'candidate_count', 0)),
            )
            for row in rows
        ],
        next_cursor=next_cursor,
        total=total,
    )


def get_clip_source(source_id: str) -> ClipSourcePayload:
    """Return one clip source."""
    row = _annotate_candidate_count(
        ClipSource.objects.filter(id=uuid.UUID(source_id)),
    ).get()
    return _to_payload(
        row,
        candidate_count=int(getattr(row, 'candidate_count', 0)),
    )
