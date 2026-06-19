"""Read-only selectors for longform review surfaces."""

import uuid
from decimal import Decimal

from server.apps.pipelines.logic.value_objects import (
    PreviewPayload,
    SceneBreakdownPayload,
    StoryboardPayload,
    StoryboardRunSummaryPayload,
    StoryboardSceneImagePayload,
    StoryboardScenePayload,
)
from server.apps.pipelines.models import (
    PipelineRun,
    StageExecution,
    StageStatus,
)
from server.common.storage import PresignUrlHelper

_TERMINAL = {
    StageStatus.SUCCEEDED,
    StageStatus.FAILED,
    StageStatus.NEEDS_INPUT,
    StageStatus.SKIPPED,
}


def _latest_parent_execution(
    run_id: str,
    stage_key: str,
) -> StageExecution | None:
    return (
        StageExecution.objects  # type: ignore[misc]
        .filter(run_id=run_id, stage_key=stage_key, parent=None)
        .order_by('-attempt')
        .first()
    )


def _active_gate_key(run: PipelineRun) -> str | None:
    gate = (
        StageExecution.objects
        .filter(run=run, parent=None, status=StageStatus.RUNNING)
        .order_by('-created_at')
        .first()
    )
    if gate is None:
        return None
    armed = set(run.channel.gates or [])
    if armed and gate.stage_key not in armed:
        return None
    return gate.stage_key


def _image_gen_state(run_id: str) -> dict[int, StageExecution]:
    """Map scene_idx → latest image_gen child execution."""
    by_scene: dict[int, StageExecution] = {}
    children = StageExecution.objects.filter(  # type: ignore[misc]
        run_id=run_id,
        stage_key='image_gen',
        parent__isnull=False,
    ).order_by('shard_index', '-attempt')
    seen_shards: set[int | None] = set()
    for child in children:
        if child.shard_index in seen_shards:
            continue
        seen_shards.add(child.shard_index)
        scene_idx = child.output.get('scene_idx')
        if scene_idx is not None:
            by_scene[int(scene_idx)] = child
    return by_scene


def _visual_prompts_map(run_id: str) -> dict[int, dict[str, object]]:
    exec_ = _latest_parent_execution(run_id, 'visual_prompts')
    if exec_ is None:
        return {}
    prompts = exec_.output.get('prompts', [])
    if not isinstance(prompts, list):
        return {}
    result: dict[int, dict[str, object]] = {}
    for item in prompts:
        if isinstance(item, dict) and item.get('scene_idx') is not None:
            result[int(item['scene_idx'])] = item
    return result


def _presign_asset(asset_id: str, presign: PresignUrlHelper) -> str:
    from server.apps.assets.models import Asset  # noqa: PLC0415

    asset = Asset.objects.get(id=asset_id)
    if not asset.file:
        return ''
    return presign.presign_get(asset.file.name or '')


def _build_scene_row(
    scene: dict[str, object],
    *,
    image_exec: StageExecution | None,
    prompt: dict[str, object] | None,
    prompt_version: int,
    presign: PresignUrlHelper,
) -> StoryboardScenePayload:
    idx = int(scene['idx'])  # type: ignore[call-overload]
    image_payload: StoryboardSceneImagePayload | None = None
    status: str = StageStatus.PENDING
    attempts = 0
    cost = Decimal(0)
    if image_exec is not None:
        status = image_exec.status
        attempts = image_exec.attempt + 1
        cost = image_exec.cost_usd
        asset_id = image_exec.output.get('asset_id')
        seed_raw = image_exec.output.get('seed')
        seed = int(seed_raw) if seed_raw is not None else None
        if asset_id:
            image_payload = StoryboardSceneImagePayload(
                asset_id=str(asset_id),
                url=_presign_asset(str(asset_id), presign),
                seed=seed,
            )
    narration = str(scene.get('narration_text', ''))
    cast_raw = scene.get('foreground_cast', [])
    cast = (
        [str(value) for value in cast_raw] if isinstance(cast_raw, list) else []
    )
    visual_prompt = (
        str(prompt.get('prompt', ''))
        if prompt
        else str(
            scene.get('visual_concept', ''),
        )
    )
    return StoryboardScenePayload(
        idx=idx,
        chapter=int(scene.get('chapter_idx', 0)),  # type: ignore[call-overload]
        beat=str(scene.get('beat', '')),
        narration=narration,
        visual_prompt=visual_prompt,
        visual_prompt_version=prompt_version,
        image=image_payload,
        status=status,
        is_hero=bool(scene.get('is_hero')),
        cast=cast,
        est_seconds=float(scene.get('est_seconds', 0)),  # type: ignore[arg-type]
        attempts=attempts,
        cost_usd=str(cost),
    )


def get_storyboard(
    run_id: str,
    presign: PresignUrlHelper,
) -> StoryboardPayload:
    """Build storyboard grid from stage outputs."""
    run = PipelineRun.objects.select_related('channel').get(
        id=uuid.UUID(run_id),
    )
    breakdown = _latest_parent_execution(run_id, 'scene_breakdown')
    scenes_raw: list[dict[str, object]] = []
    if breakdown and breakdown.output.get('scenes'):
        raw = breakdown.output['scenes']
        if isinstance(raw, list):
            scenes_raw = [s for s in raw if isinstance(s, dict)]

    prompt_version = breakdown.attempt + 1 if breakdown is not None else 0
    prompts = _visual_prompts_map(run_id)
    images = _image_gen_state(run_id)

    scenes = [
        _build_scene_row(
            scene,
            image_exec=images.get(int(scene['idx'])),  # type: ignore[call-overload]
            prompt=prompts.get(int(scene['idx'])),  # type: ignore[call-overload]
            prompt_version=prompt_version,
            presign=presign,
        )
        for scene in scenes_raw
    ]

    budget = run.channel.default_budget_usd
    return StoryboardPayload(
        run=StoryboardRunSummaryPayload(
            id=str(run.id),
            status=run.status,
            gate=_active_gate_key(run),
            spent_usd=str(run.total_cost_usd),
            projected_next_usd='0',
            budget_usd=str(budget) if budget is not None else None,
        ),
        scenes=scenes,
    )


def get_scene_breakdown(
    run_id: str,
    presign: PresignUrlHelper,
) -> SceneBreakdownPayload:
    """Return scene breakdown as storyboard scene rows."""
    storyboard = get_storyboard(run_id, presign)
    return SceneBreakdownPayload(
        scenes=storyboard.scenes,
        total=len(storyboard.scenes),
    )


def get_preview(
    run_id: str,
    presign: PresignUrlHelper,
) -> PreviewPayload:
    """Return presigned URL for latest assembly output."""
    exec_ = _latest_parent_execution(run_id, 'assembly')
    if exec_ is None or exec_.status != StageStatus.SUCCEEDED:
        return PreviewPayload(asset_id=None, url=None, duration_s=None)
    asset_id = exec_.output.get('asset_id')
    if not asset_id:
        return PreviewPayload(asset_id=None, url=None, duration_s=None)
    duration_raw = exec_.output.get('duration_s')
    duration = float(duration_raw) if duration_raw is not None else None
    return PreviewPayload(
        asset_id=str(asset_id),
        url=_presign_asset(str(asset_id), presign),
        duration_s=duration,
    )
