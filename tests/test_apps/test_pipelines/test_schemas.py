"""Tests for pipelines.schemas Pydantic output models."""

import pytest
from pydantic import ValidationError

from server.apps.pipelines.schemas import Scene, SceneBreakdownOutput


def _narration(n_words: int) -> str:
    return ' '.join(f'w{i}' for i in range(n_words))


def _valid_scene(**overrides: object) -> Scene:
    defaults: dict[str, object] = {
        'idx': 0,
        'chapter_idx': 0,
        'beat': 'intro',
        'narration_text': _narration(20),
        'visual_concept': 'Wide aerial Rome',
        'shot_type': 'aerial',
        'est_seconds': 8.0,
        'is_hero': True,
        'word_count': 20,
    }
    defaults.update(overrides)
    return Scene(**defaults)  # type: ignore[arg-type]


def test_scene_breakdown_rejects_word_count_below_5() -> None:
    """Schema envelope rejects word_count < 5; stages tighten further."""
    scene = _valid_scene(narration_text=_narration(4), word_count=4)
    with pytest.raises(ValidationError, match='word_count'):
        SceneBreakdownOutput(scenes=[scene])


def test_scene_breakdown_accepts_dense_word_count() -> None:
    """AI longform 8-16 word scenes sit inside the 5-40 schema envelope."""
    scene = _valid_scene(narration_text=_narration(8), word_count=8)
    result = SceneBreakdownOutput(scenes=[scene])
    assert result.scenes[0].word_count == 8


def test_scene_breakdown_rejects_word_count_above_40() -> None:
    """SceneBreakdownOutput.enforce_invariants rejects word_count > 40."""
    scene = _valid_scene(narration_text=_narration(41), word_count=41)
    with pytest.raises(ValidationError, match='word_count'):
        SceneBreakdownOutput(scenes=[scene])


def test_scene_setting_defaults_empty() -> None:
    """Setting is optional so older fixtures keep working."""
    scene = _valid_scene()
    assert scene.setting == ''


def test_scene_setting_is_stored() -> None:
    """Setting locks location identity for later visual prompts."""
    scene = _valid_scene(setting='Roman forum at dusk')
    assert scene.setting == 'Roman forum at dusk'


def test_scene_syncs_word_count_from_narration() -> None:
    """LLM miscounts are corrected from narration_text.split()."""
    scene = _valid_scene(word_count=15)  # narration is 20 words
    assert scene.word_count == 20
    result = SceneBreakdownOutput(scenes=[scene])
    assert result.scenes[0].word_count == 20


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


def test_footage_query_defaults() -> None:
    """Optional query fields default to empty, not None."""
    from server.apps.pipelines.schemas import FootageQuery

    query = FootageQuery(scene_idx=0, primary_query='ocean waves')
    assert query.fallback_queries == []
    assert query.negative_terms == []
    assert query.media_preference == 'any'
    assert query.orientation == 'landscape'
    assert query.era_hint == ''
    assert query.ai_fallback_prompt == ''


def test_candidate_ranking_score_is_bounded() -> None:
    """Rankings outside 0..1 are rejected by validation."""
    import pydantic

    from server.apps.pipelines.schemas import CandidateRanking

    assert CandidateRanking(external_id='a', score=1.0, reason='r').score == 1.0
    with pytest.raises(pydantic.ValidationError):
        CandidateRanking(external_id='a', score=1.5, reason='r')
    with pytest.raises(pydantic.ValidationError):
        CandidateRanking(external_id='a', score=-0.1, reason='r')


def test_footage_queries_output_holds_queries() -> None:
    """The stage output wraps a list of per-scene queries."""
    from server.apps.pipelines.schemas import (
        FootageQueriesOutput,
        FootageQuery,
    )

    output = FootageQueriesOutput(
        queries=[FootageQuery(scene_idx=0, primary_query='q')],
    )
    assert len(output.queries) == 1
    assert output.queries[0].scene_idx == 0
