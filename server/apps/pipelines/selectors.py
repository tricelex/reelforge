"""Read-only query helpers for pipeline runs."""

import base64
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from django.db.models import Q, QuerySet

from server.apps.pipelines.logic.value_objects import (
    RunDetailPayload,
    RunListPayload,
    RunSummaryPayload,
    StageSummaryPayload,
)

if TYPE_CHECKING:
    from server.apps.pipelines.models import PipelineRun, StageExecution

_MAX_PAGE_SIZE = 50


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _run_to_summary(run: 'PipelineRun') -> RunSummaryPayload:
    return RunSummaryPayload(
        id=str(run.id),
        channel_id=str(run.channel_id),
        channel_name=run.channel.name,
        topic=run.topic,
        status=run.status,
        is_paused=run.is_paused,
        total_cost_usd=str(run.total_cost_usd),
        created_at=_iso(run.created_at) or '',
        started_at=_iso(run.started_at),
        finished_at=_iso(run.finished_at),
    )


def _stage_to_summary(stage: 'StageExecution') -> StageSummaryPayload:
    return StageSummaryPayload(
        stage_key=stage.stage_key,
        status=stage.status,
        attempt=stage.attempt,
        cost_usd=str(stage.cost_usd),
        started_at=_iso(stage.started_at),
        finished_at=_iso(stage.finished_at),
    )


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    ts_str, run_id_str = raw.split('|', maxsplit=1)
    return datetime.fromisoformat(ts_str), uuid.UUID(run_id_str)


def _encode_cursor(run: 'PipelineRun') -> str:
    raw = f'{run.created_at.isoformat()}|{run.id}'
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _apply_run_filters(
    qs: QuerySet['PipelineRun'],
    *,
    status: str | None,
    channel_id: str | None,
) -> QuerySet['PipelineRun']:
    if status:
        qs = qs.filter(status=status)
    if channel_id:
        qs = qs.filter(channel_id=uuid.UUID(channel_id))
    return qs


def list_runs(
    *,
    status: str | None = None,
    channel_id: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> RunListPayload:
    """Return a cursor-paginated list of pipeline runs."""
    from server.apps.pipelines.models import PipelineRun  # noqa: PLC0415

    page_size = min(max(limit, 1), _MAX_PAGE_SIZE)
    qs = (
        PipelineRun.objects
        .select_related('channel')
        .order_by('-created_at', '-id')
    )
    qs = _apply_run_filters(qs, status=status, channel_id=channel_id)
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

    return RunListPayload(
        items=[_run_to_summary(r) for r in items],
        next_cursor=next_cursor,
        total=total,
    )


def get_run_detail(run_id: str) -> RunDetailPayload:
    """Return full run detail with latest stage attempts."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineRun,
        StageExecution,
    )

    run = (
        PipelineRun.objects
        .select_related('channel', 'blueprint')
        .get(id=uuid.UUID(run_id))
    )
    latest: dict[str, StageExecution] = {}
    for stage in (
        StageExecution.objects
        .filter(run=run, parent=None)
        .order_by('stage_key', '-attempt')
    ):
        if stage.stage_key not in latest:
            latest[stage.stage_key] = stage

    return RunDetailPayload(
        id=str(run.id),
        channel_id=str(run.channel_id),
        channel_name=run.channel.name,
        blueprint_name=run.blueprint.name,
        topic=run.topic,
        status=run.status,
        is_paused=run.is_paused,
        total_cost_usd=str(run.total_cost_usd),
        created_at=_iso(run.created_at) or '',
        started_at=_iso(run.started_at),
        finished_at=_iso(run.finished_at),
        stages=[_stage_to_summary(s) for s in latest.values()],
    )
