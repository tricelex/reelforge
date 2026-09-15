"""Tests for shared scene-window timing resolution."""

from unittest.mock import MagicMock

from server.apps.pipelines.logic.scene_timing import (
    estimated_scene_windows,
    resolve_scene_windows,
)


class TestEstimatedSceneWindows:
    """Tests for estimated_scene_windows."""

    def test_cumulative_windows_ordered_by_idx(self) -> None:
        """Scenes are ordered by idx and given cumulative start/end times."""
        scenes = [
            {'idx': 1, 'est_seconds': 5.0},
            {'idx': 0, 'est_seconds': 10.0},
        ]
        windows = estimated_scene_windows(scenes)
        assert windows[0]['scene_idx'] == 0
        assert windows[0]['start_s'] == 0.0
        assert windows[0]['end_s'] == 10.0
        assert windows[1]['scene_idx'] == 1
        assert windows[1]['start_s'] == 10.0
        assert windows[1]['end_s'] == 15.0

    def test_default_duration_when_missing(self) -> None:
        """A scene missing est_seconds defaults to 8.0 seconds."""
        windows = estimated_scene_windows([{'idx': 0}])
        assert windows[0]['end_s'] == 8.0


class TestResolveSceneWindows:
    """Tests for resolve_scene_windows."""

    def test_prefers_alignment_scenes(self) -> None:
        """Alignment scenes are used directly when present."""
        ctx = MagicMock()
        ctx.upstream = {
            'alignment': {
                'scenes': [{'scene_idx': 0, 'start_s': 1.0, 'end_s': 2.0}],
            },
        }
        result = resolve_scene_windows(ctx)
        assert result == [{'scene_idx': 0, 'start_s': 1.0, 'end_s': 2.0}]

    def test_alignment_filters_non_dict_entries(self) -> None:
        """Non-dict entries in alignment scenes are filtered out."""
        ctx = MagicMock()
        ctx.upstream = {'alignment': {'scenes': [{'a': 1}, 'garbage']}}
        result = resolve_scene_windows(ctx)
        assert result == [{'a': 1}]

    def test_falls_back_to_estimated_windows(self) -> None:
        """Missing/empty alignment falls back to estimated scene windows."""
        ctx = MagicMock()
        ctx.upstream = {
            'scene_breakdown': {'scenes': [{'idx': 0, 'est_seconds': 4.0}]},
        }
        result = resolve_scene_windows(ctx)
        assert result[0]['scene_idx'] == 0
        assert result[0]['end_s'] == 4.0

    def test_falls_back_when_breakdown_scenes_not_a_list(self) -> None:
        """A non-list scene_breakdown.scenes value is treated as empty."""
        ctx = MagicMock()
        ctx.upstream = {'scene_breakdown': {'scenes': 'garbage'}}
        assert resolve_scene_windows(ctx) == []

    def test_falls_back_when_no_upstream_at_all(self) -> None:
        """Completely empty upstream resolves to an empty scene list."""
        ctx = MagicMock()
        ctx.upstream = {}
        assert resolve_scene_windows(ctx) == []
