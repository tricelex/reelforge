"""Business logic for longform review (scene edits, publish)."""

import asyncio
import uuid
from typing import Any, cast, final

import attrs
from django.core.exceptions import ValidationError

from server.apps.pipelines.logic.constants import GATE_PARKED_STATUSES
from server.apps.pipelines.logic.value_objects import (
    FootageStoryboardPayload,
    PreviewPayload,
    PublishMetadataPatchPayload,
    PublishMetadataPayload,
    PublishPayload,
    PublishResultPayload,
    RunActionResultPayload,
    SceneBreakdownPayload,
    ScenePatchPayload,
    StoryboardPayload,
    StoryboardScenePayload,
)
from server.apps.pipelines.models import (
    PipelineRun,
    StageExecution,
    StageStatus,
)
from server.apps.pipelines.review import dispatch
from server.apps.pipelines.services.orchestrator import rerun_stage_impl
from server.apps.pipelines.storyboard_selectors import (
    _gate_stage_keys,
    _latest_parent_execution,
    get_preview,
    get_storyboard,
)
from server.apps.pipelines.storyboard_selectors import (
    get_scene_breakdown as _get_scene_breakdown,
)
from server.apps.pipelines.enqueue import kiq_advance_pipeline
from server.common.storage import PresignUrlHelper

_TERMINAL = {
    StageStatus.SUCCEEDED,
    StageStatus.FAILED,
    StageStatus.NEEDS_INPUT,
    StageStatus.SKIPPED,
}


def _mark_manual_edit_sync(run_id: str) -> None:
    PipelineRun.objects.filter(id=uuid.UUID(run_id)).update(
        had_manual_edits=True,
    )


def _stale_downstream_sync(run_id: str, from_stage_key: str) -> None:
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        _downstream_stage_keys,
    )

    run = PipelineRun.objects.get(id=uuid.UUID(run_id))
    graph: list[dict[str, Any]] = run.blueprint_snapshot.get('stages', [])
    stale_keys = _downstream_stage_keys(graph, from_stage_key)
    StageExecution.objects.filter(
        run=run,
        stage_key__in=stale_keys,
        status__in=_TERMINAL,
    ).update(status=StageStatus.STALE)


def _resolve_publish_gate(run: PipelineRun, gate_key: str | None) -> str:
    if gate_key:
        return gate_key
    parked = (
        StageExecution.objects
        .filter(
            run=run,
            parent=None,
            stage_key__in=_gate_stage_keys(run),
            status__in=GATE_PARKED_STATUSES,
        )
        .order_by('-created_at')
        .first()
    )
    if parked is not None:
        return parked.stage_key
    for candidate in ('final_gate', 'review_gate', 'storyboard_gate'):
        if candidate in (run.channel.gates or []):
            return candidate
    msg = 'No publish gate is active for this run'
    raise ValidationError(msg)


def _find_scene(
    scenes_raw: list[object],
    scene_idx: int,
) -> dict[str, object]:
    for item in scenes_raw:
        if isinstance(item, dict) and int(item.get('idx', -1)) == scene_idx:
            return item
    msg = f'scene {scene_idx} not found'
    raise ValidationError(msg)


def _apply_scene_fields(
    scene: dict[str, object],
    payload: ScenePatchPayload,
) -> None:
    if payload.narration_text is not None:
        scene['narration_text'] = payload.narration_text
        scene['word_count'] = len(payload.narration_text.split())
    if payload.visual_concept is not None:
        scene['visual_concept'] = payload.visual_concept
    if payload.is_hero is not None:
        scene['is_hero'] = payload.is_hero
    if payload.foreground_cast is not None:
        scene['foreground_cast'] = payload.foreground_cast


def _update_prompt_row(
    prompt: dict[str, object],
    scene_idx: int,
    payload: ScenePatchPayload,
) -> None:
    if int(prompt.get('scene_idx', -1)) != scene_idx:  # type: ignore[call-overload]
        return
    if payload.visual_prompt is not None:
        prompt['prompt'] = payload.visual_prompt
    elif payload.visual_concept is not None:
        prompt['prompt'] = payload.visual_concept


def _latest_footage_search_shard(
    run_id: str,
    scene_idx: int,
) -> StageExecution | None:
    """Return the latest footage_search child execution for one scene."""
    rows = StageExecution.objects.filter(
        run_id=uuid.UUID(run_id),
        stage_key='footage_search',
        parent__isnull=False,
    ).order_by('shard_index', '-attempt')
    for row in rows:
        idx = row.output.get('scene_idx')
        if idx is not None and int(idx) == scene_idx:
            return row
    return None


def _sync_visual_prompts(
    run_id: str,
    scene_idx: int,
    payload: ScenePatchPayload,
) -> str:
    vp_exec = _latest_parent_execution(run_id, 'visual_prompts')
    if vp_exec is None or vp_exec.status != StageStatus.SUCCEEDED:
        return 'scene_breakdown'

    vp_output = dict(vp_exec.output)
    prompts_raw = vp_output.get('prompts', [])
    if not isinstance(prompts_raw, list):
        return 'scene_breakdown'

    for prompt in prompts_raw:
        if isinstance(prompt, dict):
            _update_prompt_row(prompt, scene_idx, payload)

    vp_exec.output = {**vp_output, 'prompts': prompts_raw}
    vp_exec.save(update_fields=['output'])
    return 'visual_prompts'


@final
@attrs.define(slots=True, frozen=True)
class RunReviewService:
    """Patch scenes and trigger publish for longform review."""

    _presign: PresignUrlHelper

    def get_storyboard(
        self,
        run_id: str,
    ) -> StoryboardPayload | FootageStoryboardPayload:
        """Return storyboard payload for this run's blueprint profile."""
        return cast(
            'StoryboardPayload | FootageStoryboardPayload',
            dispatch.get_storyboard(run_id, self._presign),
        )

    def get_scene_breakdown(self, run_id: str) -> SceneBreakdownPayload:
        """Return scene breakdown payload."""
        return _get_scene_breakdown(run_id, self._presign)

    def get_preview(self, run_id: str) -> PreviewPayload:
        """Return assembly preview URL."""
        return get_preview(run_id, self._presign)

    def get_publish_metadata(self, run_id: str) -> PublishMetadataPayload:
        """Return metadata stage output for final review."""
        meta_exec = _latest_parent_execution(run_id, 'metadata')
        if meta_exec is None or meta_exec.status != StageStatus.SUCCEEDED:
            return PublishMetadataPayload(
                title='',
                description='',
                tags=[],
                category='Education',
                thumbnail_asset_id=None,
            )
        meta = meta_exec.output
        tags_raw = meta.get('tags', [])
        tags = (
            [str(tag) for tag in tags_raw] if isinstance(tags_raw, list) else []
        )
        thumb = meta.get('thumbnail_asset_id')
        return PublishMetadataPayload(
            title=str(meta.get('title', '')),
            description=str(meta.get('description', '')),
            tags=tags,
            category=str(meta.get('category', 'Education')),
            thumbnail_asset_id=str(thumb) if thumb else None,
        )

    def patch_publish_metadata(
        self,
        run_id: str,
        payload: PublishMetadataPatchPayload,
    ) -> PublishMetadataPayload:
        """Merge edits into metadata stage output."""
        meta_exec = _latest_parent_execution(run_id, 'metadata')
        if meta_exec is None:
            msg = 'metadata stage output is not available'
            raise ValidationError(msg)
        meta = dict(meta_exec.output)
        if payload.title is not None:
            meta['title'] = payload.title
        if payload.description is not None:
            meta['description'] = payload.description
        if payload.tags is not None:
            meta['tags'] = payload.tags
        if payload.category is not None:
            meta['category'] = payload.category
        if payload.thumbnail_asset_id is not None:
            meta['thumbnail_asset_id'] = payload.thumbnail_asset_id
        meta_exec.output = meta
        meta_exec.save(update_fields=['output'])
        _mark_manual_edit_sync(run_id)
        return self.get_publish_metadata(run_id)

    def patch_scene(
        self,
        run_id: str,
        scene_idx: int,
        payload: ScenePatchPayload,
    ) -> StoryboardScenePayload:
        """Update one scene and stale downstream stages."""
        payload_dict: dict[str, Any] = {
            'narration_text': payload.narration_text,
            'visual_concept': payload.visual_concept,
            'visual_prompt': payload.visual_prompt,
            'is_hero': payload.is_hero,
            'foreground_cast': payload.foreground_cast,
        }
        # ai_visual.apply_scene_edit already stales downstream stages and
        # marks had_manual_edits itself. The result is always ai_visual
        # shaped (this method's return type), so the lookup below goes
        # straight to that selector rather than back through dispatch.
        dispatch.apply_scene_edit(run_id, scene_idx, payload_dict)

        board = get_storyboard(run_id, self._presign)
        for row in board.scenes:
            if row.idx == scene_idx:
                return row
        msg = f'scene {scene_idx} not found after patch'
        raise ValidationError(msg)

    def select_footage_candidate(
        self,
        run_id: str,
        scene_idx: int,
        external_id: str,
    ) -> RunActionResultPayload:
        """Swap a scene's footage for a ranked alternate candidate.

        Requeues only the ``footage_prep`` shard for this scene, leaving
        sibling scenes untouched.
        """
        shard = _latest_footage_search_shard(run_id, scene_idx)
        candidates = (
            shard.output.get('candidates', []) if shard is not None else []
        )
        candidate = next(
            (
                c
                for c in candidates
                if isinstance(c, dict)
                and str(c.get('external_id')) == external_id
            ),
            None,
        )
        if shard is None or candidate is None:
            msg = f'Unknown footage candidate: {external_id}'
            raise ValidationError(msg)

        shard.output = {
            **dict(shard.output),
            'source': str(candidate.get('provider', '')),
            'license': str(candidate.get('license', '')),
            'attribution': str(candidate.get('author', '')),
            'source_url': str(candidate.get('source_url', '')),
            'selected_external_id': external_id,
        }
        shard.save(update_fields=['output'])

        asyncio.run(
            rerun_stage_impl(
                run_id,
                'footage_prep',
                shard_indices=[scene_idx],
            ),
        )
        return RunActionResultPayload(status='queued')

    def research_footage(
        self,
        run_id: str,
        scene_idx: int,
        query: str,
    ) -> RunActionResultPayload:
        """Re-run footage_search for one scene with an operator query."""
        trimmed = query.strip()
        if not trimmed:
            msg = 'query must not be empty'
            raise ValidationError(msg)

        shard = _latest_footage_search_shard(run_id, scene_idx)
        if shard is not None:
            shard.input_snapshot = {
                **dict(shard.input_snapshot),
                'primary_query': trimmed,
            }
            shard.save(update_fields=['input_snapshot'])

        asyncio.run(
            rerun_stage_impl(
                run_id,
                'footage_search',
                shard_indices=[scene_idx],
            ),
        )
        return RunActionResultPayload(status='queued')

    def publish(
        self,
        run_id: str,
        payload: PublishPayload,
    ) -> PublishResultPayload:
        """Approve final gate and resume pipeline toward publish stage."""
        from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
            _approve_gate_sync,
        )

        run = PipelineRun.objects.select_related('channel').get(
            id=uuid.UUID(run_id),
        )
        gate_key = _resolve_publish_gate(run, payload.gate_key)

        if payload.metadata_patch:
            meta_exec = _latest_parent_execution(run_id, 'metadata')
            if (
                meta_exec is not None
                and meta_exec.status == StageStatus.SUCCEEDED
            ):
                meta = dict(meta_exec.output)
                meta.update(payload.metadata_patch)
                meta_exec.output = meta
                meta_exec.save(update_fields=['output'])

        output: dict[str, object] = {}
        if payload.thumbnail_asset_id is not None:
            output['thumbnail_asset_id'] = payload.thumbnail_asset_id
        if payload.schedule_at is not None:
            output['schedule_at'] = payload.schedule_at

        _approve_gate_sync(run_id, gate_key, output)
        kiq_advance_pipeline(run_id)

        run.refresh_from_db()
        job_id: str | None = None
        latest_job = run.publish_jobs.order_by('-created_at').first()
        if latest_job is not None:
            job_id = str(latest_job.id)

        return PublishResultPayload(
            status='ok',
            gate_key=gate_key,
            publish_job_id=job_id,
        )
