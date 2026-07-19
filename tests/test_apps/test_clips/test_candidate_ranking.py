"""Tests for deterministic clip candidate ranking."""

from server.apps.clips.candidate_ranking import (
    RankedClip,
    duration_bounds,
    iter_transcript_windows,
    normalize_raw_clips,
)
from server.apps.clips.logic.constants import (
    ClipLengthBucket,
    compute_virality_score,
    score_to_letter_grade,
)


class _Raw:
    def __init__(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_compute_virality_score_weights() -> None:
    score = compute_virality_score(
        hook_score=100,
        flow_score=0,
        value_score=0,
        trend_score=0,
    )
    assert score == 30.0


def test_score_to_letter_grade() -> None:
    assert score_to_letter_grade(97) == 'A+'
    assert score_to_letter_grade(91) == 'A-'
    assert score_to_letter_grade(50) == 'F'


def test_duration_bounds_standard_and_custom() -> None:
    assert duration_bounds(ClipLengthBucket.UNDER_30)[1] < 30
    lo, hi = duration_bounds(
        ClipLengthBucket.CUSTOM,
        custom_min_sec=40,
        custom_max_sec=55,
    )
    assert lo == 40
    assert hi == 55


def test_iter_transcript_windows_overlaps() -> None:
    windows = iter_transcript_windows(
        [],
        video_duration=50 * 60,
        window_size_sec=20 * 60,
        overlap_sec=2 * 60,
    )
    assert len(windows) >= 3
    assert windows[0][0] == 0.0


def test_normalize_raw_clips_dedupes_and_ranks() -> None:
    words = [
        {'word': 'a', 'start': 0.0, 'end': 0.2},
        {'word': 'b', 'start': 40.0, 'end': 40.2},
        {'word': 'c', 'start': 80.0, 'end': 80.2},
        {'word': 'd', 'start': 120.0, 'end': 120.2},
    ]
    raw = [
        _Raw(
            start_sec=10,
            end_sec=50,
            title='Low',
            hook_text='h',
            caption_template='',
            headline='h',
            reason='r',
            hook_score=60,
            flow_score=60,
            value_score=60,
            trend_score=60,
            intent_match_score=50,
            confidence=60,
            hook_reason='',
            flow_reason='',
            value_reason='',
            trend_reason='',
        ),
        _Raw(
            start_sec=12,
            end_sec=52,
            title='High',
            hook_text='h',
            caption_template='',
            headline='h',
            reason='r',
            hook_score=95,
            flow_score=90,
            value_score=92,
            trend_score=88,
            intent_match_score=80,
            confidence=90,
            hook_reason='',
            flow_reason='',
            value_reason='',
            trend_reason='',
        ),
        _Raw(
            start_sec=90,
            end_sec=130,
            title='Other',
            hook_text='h',
            caption_template='',
            headline='h',
            reason='r',
            hook_score=80,
            flow_score=80,
            value_score=80,
            trend_score=80,
            intent_match_score=70,
            confidence=80,
            hook_reason='',
            flow_reason='',
            value_reason='',
            trend_reason='',
        ),
    ]
    ranked = normalize_raw_clips(
        raw,
        enriched_words=words,
        scene_cuts=[],
        video_duration=200.0,
        length_bucket=ClipLengthBucket.FROM_30_TO_59,
        clips_requested=2,
    )
    assert len(ranked) == 2
    assert ranked[0].title == 'High'
    assert isinstance(ranked[0], RankedClip)
    assert ranked[0].virality_score > ranked[1].virality_score
