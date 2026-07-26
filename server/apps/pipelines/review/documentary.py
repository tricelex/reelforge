"""Documentary review adapter — footage storyboard and scene edits."""

import uuid
from typing import Any

from server.apps.pipelines.logic.value_objects import (
    FootageCandidatePayload,
    FootageSceneRow,
    FootageStoryboardPayload,
    StoryboardRunSummaryPayload,
)
from server.apps.pipelines.models import (
    PipelineRun,
    StageExecution,
    StageStatus,
)
from server.apps.pipelines.storyboard_selectors import _active_gate_key
from server.common.storage import PresignUrlHelper

_AI_SOURCE = 'ai_flux'


def _latest_parent_output(run_id: str, stage_key: str) -> dict[str, Any]:
    """Return the latest successful parent execution output for a stage."""
    row = (
        StageExecution.objects
        .filter(
            run_id=uuid.UUID(run_id),
            stage_key=stage_key,
            parent=None,
            status=StageStatus.SUCCEEDED,
        )
        .order_by('-attempt', '-created_at')
        .first()
    )
    return dict(row.output) if row and isinstance(row.output, dict) else {}


def _footage_state(run_id: str) -> dict[int, StageExecution]:
    """Map scene_idx → latest footage_search child execution."""
    state: dict[int, StageExecution] = {}
    rows = StageExecution.objects.filter(
        run_id=uuid.UUID(run_id),
        stage_key='footage_search',
        parent__isnull=False,
    ).order_by('shard_index', '-attempt')
    for row in rows:
        idx = row.output.get('scene_idx')
        if idx is None or int(idx) in state:
            continue
        state[int(idx)] = row
    return state


def _presign_asset(
    asset_id: str,
    presign: PresignUrlHelper,
) -> str | None:
    """Return a presigned URL for a pipeline asset, or None."""
    from server.apps.assets.models import Asset  # noqa: PLC0415

    asset = Asset.objects.filter(id=asset_id).first()
    if asset is None or not asset.file:
        return None
    return presign.presign_get(asset.file.name or '')


def _candidate_payloads(
    output: dict[str, Any],
) -> list[FootageCandidatePayload]:
    """Map stored candidate dicts to API payloads."""
    return [
        FootageCandidatePayload(
            external_id=str(c.get('external_id', '')),
            provider=str(c.get('provider', '')),
            thumb_url=str(c.get('thumb_url', '')),
            preview_url=str(c.get('preview_url', '')),
            width=int(c.get('width') or 0),
            height=int(c.get('height') or 0),
            duration_s=(
                float(c['duration_s'])
                if c.get('duration_s') is not None
                else None
            ),
            license=str(c.get('license', '')),
            author=str(c.get('author', '')),
            source_url=str(c.get('source_url', '')),
        )
        for c in output.get('candidates', [])
    ]


def _scene_row(
    scene: dict[str, Any],
    execution: StageExecution | None,
    presign: PresignUrlHelper,
) -> FootageSceneRow:
    """Build one documentary storyboard row."""
    output = dict(execution.output) if execution else {}
    asset_id = output.get('asset_id')
    return FootageSceneRow(
        idx=int(scene['idx']),
        narration_text=str(scene.get('narration_text', '')),
        visual_concept=str(scene.get('visual_concept', '')),
        status=execution.status if execution else StageStatus.PENDING,
        est_seconds=float(scene.get('est_seconds', 0.0)),
        asset_url=(
            _presign_asset(str(asset_id), presign) if asset_id else None
        ),
        media_type=str(output.get('media_type', '')),
        source=str(output.get('source', '')),
        license=str(output.get('license', '')),
        license_url=str(output.get('license_url', '')),
        attribution_required=bool(output.get('attribution_required')),
        author=str(output.get('attribution', '')),
        source_url=str(output.get('source_url', '')),
        rerank_score=(
            float(output['rerank_score'])
            if output.get('rerank_score') is not None
            else None
        ),
        candidates=_candidate_payloads(output),
    )


def get_storyboard(
    run_id: str,
    presign: PresignUrlHelper,
) -> FootageStoryboardPayload:
    """Build the documentary storyboard from footage_search outputs."""
    run = PipelineRun.objects.select_related('channel').get(
        id=uuid.UUID(run_id),
    )
    breakdown = _latest_parent_output(run_id, 'scene_breakdown')
    raw_scenes = breakdown.get('scenes') or []
    scenes_raw = [s for s in raw_scenes if isinstance(s, dict)]
    state = _footage_state(run_id)

    rows = [
        _scene_row(scene, state.get(int(scene['idx'])), presign)
        for scene in scenes_raw
    ]
    ai_fallback_count = sum(1 for row in rows if row.source == _AI_SOURCE)
    budget = run.channel.default_budget_usd

    return FootageStoryboardPayload(
        profile='documentary_footage',
        run=StoryboardRunSummaryPayload(
            id=str(run.id),
            status=run.status,
            gate=_active_gate_key(run),
            spent_usd=str(run.total_cost_usd),
            projected_next_usd='0',
            budget_usd=str(budget) if budget is not None else None,
        ),
        scenes=rows,
        ai_fallback_count=ai_fallback_count,
    )


def _apply_edit_to_scene(
    scene: dict[str, Any],
    scene_idx: int,
    payload: dict[str, Any],
) -> None:
    """Merge editable text fields into one scene dict, in place."""
    if int(scene.get('idx', -1)) != scene_idx:
        return
    for field in ('narration_text', 'visual_concept'):
        if payload.get(field) is not None:
            scene[field] = payload[field]


def apply_scene_edit(
    run_id: str,
    scene_idx: int,
    payload: dict[str, Any],
) -> str:
    """Write an edited scene back to scene_breakdown; stale footage_queries.

    Returns the stage key downstream consumers must be staled from — for
    documentary runs the queries, not the AI visual prompts.
    """
    row = (
        StageExecution.objects
        .filter(
            run_id=uuid.UUID(run_id),
            stage_key='scene_breakdown',
            parent=None,
            status=StageStatus.SUCCEEDED,
        )
        .order_by('-attempt', '-created_at')
        .first()
    )
    if row is None:
        return 'footage_queries'

    output = dict(row.output)
    scenes = list(output.get('scenes') or [])
    for scene in scenes:
        if isinstance(scene, dict):
            _apply_edit_to_scene(scene, scene_idx, payload)
    output['scenes'] = scenes
    row.output = output
    row.save(update_fields=['output'])
    return 'footage_queries'
