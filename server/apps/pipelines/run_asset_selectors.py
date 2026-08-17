"""Read-only selectors for pipeline blueprints and run assets."""

import uuid
from typing import TYPE_CHECKING

from server.apps.pipelines.logic.value_objects import (
    BlueprintDetailPayload,
    BlueprintListPayload,
    BlueprintSummaryPayload,
    RunAssetListPayload,
    RunAssetPayload,
)
from server.apps.pipelines.models import PipelineBlueprint
from server.common.pagination import paginate_queryset
from server.common.storage import PresignUrlHelper

if TYPE_CHECKING:
    from server.apps.assets.models import Asset
    from server.apps.pipelines.models import StageExecution

_SCENE_LABEL_STAGES = frozenset({
    'image_gen',
    'motion',
    'footage_search',
    'footage_prep',
})
_STATIC_LABELS = {
    'assembly': 'assembled video',
    'thumbnail': 'thumbnail',
    'alignment': 'captions',
}


def _clip_label(output: dict[str, object]) -> str:
    """Return a human label for a rendered clip asset."""
    from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

    candidate_id = output.get('candidate_id')
    if not candidate_id:
        return 'clip'
    title = (
        ClipCandidate.objects
        .filter(id=str(candidate_id))
        .values_list('title', flat=True)
        .first()
    )
    return f'clip: {title}' if title else 'clip'


def _indexed_label(prefix: str, idx: object) -> str | None:
    """Return ``prefix n`` for a fan-out shard, or None when unknown."""
    return f'{prefix} {idx}' if idx is not None else None


def _asset_label(stage_exec: 'StageExecution | None') -> str | None:
    """Build a short human-friendly label from the producing stage."""
    if stage_exec is None:
        return None
    key = stage_exec.stage_key
    output = stage_exec.output or {}
    if key in _SCENE_LABEL_STAGES:
        return _indexed_label(
            'scene',
            output.get('scene_idx', stage_exec.shard_index),
        )
    if key == 'tts':
        return _indexed_label(
            'chapter',
            output.get('chapter_idx', stage_exec.shard_index),
        )
    if key == 'clip_render':
        return _clip_label(output)
    return _STATIC_LABELS.get(key)


def asset_to_payload(
    asset: 'Asset',
    presign: PresignUrlHelper,
) -> RunAssetPayload:
    """Build a presigned, stage-attributed RunAssetPayload."""
    stage_exec = asset.stage_execution
    return RunAssetPayload(
        id=str(asset.id),
        kind=asset.kind,
        mime=asset.mime,
        url=presign.presign_get(asset.file.name or '') if asset.file else '',
        stage_key=stage_exec.stage_key if stage_exec is not None else None,
        label=_asset_label(stage_exec),
    )


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


def _blueprint_to_detail(row: PipelineBlueprint) -> BlueprintDetailPayload:
    graph = row.graph if isinstance(row.graph, dict) else {}
    return BlueprintDetailPayload(
        id=str(row.id),
        name=row.name,
        kind=row.kind,
        version=row.version,
        is_active=row.is_active,
        graph=dict(graph),
    )


def get_blueprint_detail(blueprint_id: str) -> BlueprintDetailPayload:
    """Return one blueprint including its graph."""
    row = PipelineBlueprint.objects.get(id=uuid.UUID(blueprint_id))
    return _blueprint_to_detail(row)


def list_run_assets(
    run_id: str,
    presign: PresignUrlHelper,
    *,
    cursor: str | None = None,
    limit: int = 20,
) -> RunAssetListPayload:
    """Return presigned URLs for assets owned by a run."""
    from server.apps.assets.models import Asset  # noqa: PLC0415

    qs = (
        Asset.objects
        .filter(run_id=uuid.UUID(run_id))
        .select_related('stage_execution')
        .order_by('-created_at', '-id')
    )
    rows, next_cursor, total = paginate_queryset(
        qs,
        cursor=cursor,
        limit=limit,
    )
    items = [asset_to_payload(asset, presign) for asset in rows]
    return RunAssetListPayload(
        items=items,
        next_cursor=next_cursor,
        total=total,
    )
