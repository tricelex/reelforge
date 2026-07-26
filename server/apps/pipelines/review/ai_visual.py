"""AI-visual review adapter — delegates to the original selectors.

This module exists so `dispatch` has a uniform interface for both profiles
without modifying `storyboard_selectors` or `run_review`. There is no
standalone `apply_scene_edit` function in `run_review.py` today — the public
entry point is `RunReviewService.patch_scene`, which returns the updated
storyboard row rather than the stale-from stage key `dispatch` needs. Rather
than modify that method's return type (forbidden by this task), this adapter
replays the same scene-patch + visual-prompt-sync steps using the private
helpers `run_review.py` already exposes at module scope.
"""

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from server.apps.pipelines.logic.value_objects import (
    ScenePatchPayload,
    StoryboardPayload,
)
from server.common.storage import PresignUrlHelper


def get_storyboard(
    run_id: str,
    presign: PresignUrlHelper,
) -> StoryboardPayload:
    """Return the AI-visual storyboard payload."""
    from server.apps.pipelines.storyboard_selectors import (  # noqa: PLC0415
        get_storyboard as _get,
    )

    return _get(run_id, presign)


def _scene_patch_from_dict(payload: dict[str, Any]) -> ScenePatchPayload:
    """Build a `ScenePatchPayload` from a raw request dict."""
    return ScenePatchPayload(
        narration_text=payload.get('narration_text'),
        visual_concept=payload.get('visual_concept'),
        visual_prompt=payload.get('visual_prompt'),
        is_hero=payload.get('is_hero'),
        foreground_cast=payload.get('foreground_cast'),
    )


def apply_scene_edit(
    run_id: str,
    scene_idx: int,
    payload: dict[str, Any],
) -> str:
    """Apply a scene text edit and return the stage to stale from."""
    from server.apps.pipelines.models import StageStatus  # noqa: PLC0415
    from server.apps.pipelines.services.run_review import (  # noqa: PLC0415
        _apply_scene_fields,
        _find_scene,
        _mark_manual_edit_sync,
        _stale_downstream_sync,
        _sync_visual_prompts,
    )
    from server.apps.pipelines.storyboard_selectors import (  # noqa: PLC0415
        _latest_parent_execution,
    )

    scene_payload = _scene_patch_from_dict(payload)
    breakdown = _latest_parent_execution(run_id, 'scene_breakdown')
    if breakdown is None or breakdown.status != StageStatus.SUCCEEDED:
        msg = 'scene_breakdown output is not available'
        raise ValidationError(msg)

    output = dict(breakdown.output)
    scenes_raw = output.get('scenes', [])
    if not isinstance(scenes_raw, list):
        msg = 'invalid scene_breakdown output'
        raise ValidationError(msg)

    scene = _find_scene(scenes_raw, scene_idx)
    _apply_scene_fields(scene, scene_payload)

    with transaction.atomic():
        breakdown.output = {**output, 'scenes': scenes_raw}
        breakdown.save(update_fields=['output'])
        stale_from = _sync_visual_prompts(run_id, scene_idx, scene_payload)
        _stale_downstream_sync(run_id, stale_from)

    _mark_manual_edit_sync(run_id)
    return stale_from
