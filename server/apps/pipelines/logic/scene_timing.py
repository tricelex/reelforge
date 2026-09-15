"""Shared scene-window timing resolution for editor-handoff stages.

Prefers exact ``alignment`` scene timing when the render pipeline has run
TTS + forced alignment. Falls back to cumulative estimates from
``scene_breakdown``'s ``est_seconds`` when it has not — e.g. script-only
handoff blueprints that skip audio/video rendering entirely.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.apps.pipelines.stages.base import StageContext

_MAX_ROWS = 5000


def estimated_scene_windows(
    scenes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fabricate start_s/end_s for scene_breakdown scenes via est_seconds.

    Used only when ``alignment`` has not run yet (or was skipped) so
    downstream stages still get a usable, if approximate, timeline.
    """
    ordered = sorted(scenes, key=lambda s: int(s['idx']))
    windows: list[dict[str, Any]] = []
    cursor = 0.0
    for i, scene in enumerate(ordered):
        assert i < _MAX_ROWS, 'scene index exceeded bound'  # noqa: S101
        duration = float(scene.get('est_seconds', 8.0))
        windows.append({
            **scene,
            'scene_idx': int(scene['idx']),
            'start_s': cursor,
            'end_s': cursor + duration,
        })
        cursor += duration
    return windows


def resolve_scene_windows(ctx: 'StageContext') -> list[dict[str, Any]]:
    """Prefer alignment scene timing; fall back to estimated windows."""
    aligned = ctx.upstream.get('alignment', {}).get('scenes', [])
    if isinstance(aligned, list) and aligned:
        return [s for s in aligned if isinstance(s, dict)]
    breakdown_scenes = ctx.upstream.get('scene_breakdown', {}).get(
        'scenes',
        [],
    )
    scenes = breakdown_scenes if isinstance(breakdown_scenes, list) else []
    return estimated_scene_windows(
        [s for s in scenes if isinstance(s, dict)],
    )
