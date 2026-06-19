"""Read-only selectors for pipeline blueprints and run assets."""

import uuid

from server.apps.pipelines.logic.value_objects import (
    BlueprintListPayload,
    BlueprintSummaryPayload,
    RunAssetListPayload,
    RunAssetPayload,
)
from server.apps.pipelines.models import PipelineBlueprint
from server.common.pagination import paginate_queryset
from server.common.storage import PresignUrlHelper


def list_blueprints(
    *,
    cursor: str | None = None,
    limit: int = 20,
) -> BlueprintListPayload:
    """Return active pipeline blueprints."""
    qs = PipelineBlueprint.objects.filter(is_active=True).order_by(
        '-created_at',
        '-id',
    )
    rows, next_cursor, total = paginate_queryset(
        qs,
        cursor=cursor,
        limit=limit,
    )
    return BlueprintListPayload(
        items=[
            BlueprintSummaryPayload(
                id=str(row.id),
                name=row.name,
                kind=row.kind,
                version=row.version,
                is_active=row.is_active,
            )
            for row in rows
        ],
        next_cursor=next_cursor,
        total=total,
    )


def list_run_assets(
    run_id: str,
    presign: PresignUrlHelper,
    *,
    cursor: str | None = None,
    limit: int = 20,
) -> RunAssetListPayload:
    """Return presigned URLs for assets owned by a run."""
    from server.apps.assets.models import Asset  # noqa: PLC0415

    qs = Asset.objects.filter(run_id=uuid.UUID(run_id)).order_by(
        '-created_at',
        '-id',
    )
    rows, next_cursor, total = paginate_queryset(
        qs,
        cursor=cursor,
        limit=limit,
    )
    items = [
        RunAssetPayload(
            id=str(asset.id),
            kind=asset.kind,
            mime=asset.mime,
            url=presign.presign_get(asset.file.name or '')
            if asset.file
            else '',
        )
        for asset in rows
    ]
    return RunAssetListPayload(
        items=items,
        next_cursor=next_cursor,
        total=total,
    )
