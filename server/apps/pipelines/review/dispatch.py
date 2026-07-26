"""Route review requests to the adapter matching the run's profile."""

import uuid
from typing import Any

from server.apps.pipelines.logic.blueprint_profiles import (
    resolve_profile_key,
)
from server.apps.pipelines.review import ai_visual, documentary
from server.common.storage import PresignUrlHelper

_ADAPTERS = {
    'ai_visual': ai_visual,
    'documentary_footage': documentary,
}


def _load_run(run_id: str) -> Any:
    """Load the run with the fields needed to pick an adapter."""
    from server.apps.pipelines.models import PipelineRun  # noqa: PLC0415

    return PipelineRun.objects.get(id=uuid.UUID(run_id))


def _adapter(run_id: str) -> Any:
    """Return the review adapter for this run's blueprint profile."""
    run = _load_run(run_id)
    key = resolve_profile_key(run.blueprint_snapshot or {})
    return _ADAPTERS[key]


def get_storyboard(run_id: str, presign: PresignUrlHelper) -> Any:
    """Return the storyboard payload for this run's profile."""
    return _adapter(run_id).get_storyboard(run_id, presign)


def apply_scene_edit(
    run_id: str,
    scene_idx: int,
    payload: dict[str, Any],
) -> str:
    """Apply a scene edit and return the stage key to stale from."""
    return str(_adapter(run_id).apply_scene_edit(run_id, scene_idx, payload))
