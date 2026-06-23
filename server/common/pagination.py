"""Shared cursor pagination helpers."""

import base64
import uuid
from datetime import datetime

from django.db.models import Model, Q, QuerySet

MAX_PAGE_SIZE = 50


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    """Encode a pagination cursor from timestamp and row id."""
    raw = f'{created_at.isoformat()}|{row_id}'
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Decode a pagination cursor."""
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    ts_str, row_id_str = raw.split('|', maxsplit=1)
    return datetime.fromisoformat(ts_str), uuid.UUID(row_id_str)


def paginate_queryset[T: Model](
    qs: QuerySet[T],
    *,
    cursor: str | None,
    limit: int,
) -> tuple[list[T], str | None, int]:
    """Return page rows, next cursor, and total count."""
    page_size = min(max(limit, 1), MAX_PAGE_SIZE)
    total = qs.count()
    if cursor:
        cursor_dt, cursor_id = decode_cursor(cursor)
        qs = qs.filter(
            Q(created_at__lt=cursor_dt)
            | Q(created_at=cursor_dt, id__lt=cursor_id),
        )
    rows = list(qs[: page_size + 1])
    has_more = len(rows) > page_size
    items = rows[:page_size]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(last.created_at, last.id)  # type: ignore[attr-defined]
    return items, next_cursor, total
