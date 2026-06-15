"""Tests for the assembly pipeline stage."""

from unittest.mock import MagicMock

from server.apps.pipelines.stages.assembly import (
    AssemblyStage,
    _build_music_map,
    _group_scenes_by_chapter,
)


def test_assembly_stage_attributes() -> None:
    assert AssemblyStage.key == 'assembly'
    assert AssemblyStage.queue == 'render'
    assert AssemblyStage.max_retries == 1
    assert AssemblyStage.timeout_s == 3600


def test_assembly_fan_out_returns_none() -> None:
    assert AssemblyStage().fan_out(MagicMock()) is None


def test_group_scenes_by_chapter() -> None:
    scenes = [
        {'chapter_idx': 0, 'segment_idx': 0, 'start_s': 0.0, 'end_s': 5.0},
        {'chapter_idx': 0, 'segment_idx': 1, 'start_s': 5.0, 'end_s': 10.0},
        {'chapter_idx': 1, 'segment_idx': 0, 'start_s': 0.0, 'end_s': 7.0},
    ]
    result = _group_scenes_by_chapter(scenes)
    assert list(result.keys()) == [0, 1]
    assert len(result[0]) == 2
    assert len(result[1]) == 1


def test_build_music_map() -> None:
    entries = [
        {'chapter_idx': 0, 'library_asset_id': 'uuid-a', 'gain_db': -3.0},
        {'chapter_idx': 1, 'library_asset_id': 'uuid-b', 'gain_db': -6.0},
    ]
    result = _build_music_map(entries)
    assert result[0]['library_asset_id'] == 'uuid-a'
    assert result[1]['gain_db'] == -6.0
