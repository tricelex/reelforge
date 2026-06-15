"""Tests for pipelines.schemas Pydantic output models."""

import pytest
from pydantic import ValidationError

from server.apps.pipelines.schemas import Scene, SceneBreakdownOutput


def _valid_scene(**overrides: object) -> Scene:
    defaults: dict[str, object] = {
        'idx': 0,
        'chapter_idx': 0,
        'beat': 'intro',
        'narration_text': 'A dramatic turn of events unfolded.',
        'visual_concept': 'Wide aerial Rome',
        'shot_type': 'aerial',
        'est_seconds': 8.0,
        'is_hero': True,
        'word_count': 20,
    }
    defaults.update(overrides)
    return Scene(**defaults)  # type: ignore[arg-type]


def test_scene_breakdown_rejects_word_count_below_10() -> None:
    """SceneBreakdownOutput.enforce_invariants rejects word_count < 10."""
    scene = _valid_scene(word_count=5)
    with pytest.raises(ValidationError, match='word_count'):
        SceneBreakdownOutput(scenes=[scene])


def test_scene_breakdown_rejects_word_count_above_35() -> None:
    """SceneBreakdownOutput.enforce_invariants rejects word_count > 35."""
    scene = _valid_scene(word_count=36)
    with pytest.raises(ValidationError, match='word_count'):
        SceneBreakdownOutput(scenes=[scene])


def test_scene_breakdown_rejects_more_than_two_foreground_cast() -> None:
    """SceneBreakdownOutput.enforce_invariants rejects > 2 foreground_cast entries."""
    scene = _valid_scene(foreground_cast=['alice', 'bob', 'carol'])
    with pytest.raises(ValidationError, match='foreground'):
        SceneBreakdownOutput(scenes=[scene])


def test_scene_breakdown_valid_passes() -> None:
    """A valid SceneBreakdownOutput passes all invariants."""
    result = SceneBreakdownOutput(scenes=[_valid_scene()])
    assert len(result.scenes) == 1
    assert result.scenes[0].is_hero is True
