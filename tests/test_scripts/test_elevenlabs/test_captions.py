"""Tests for scripts/elevenlabs/captions.py."""

from scripts.elevenlabs.captions import (
    build_srt,
    chunk_words_into_cues,
    fmt_srt_time,
    normalize_words,
)


def test_normalize_words_maps_text_field_to_word() -> None:
    raw = [{'text': 'Rome', 'start': 0.0, 'end': 0.4, 'loss': 0.1}]
    assert normalize_words(raw) == [
        {'word': 'Rome', 'start': 0.0, 'end': 0.4},
    ]


def test_normalize_words_drops_whitespace_only_tokens() -> None:
    raw = [
        {'text': 'Rome', 'start': 0.0, 'end': 0.4},
        {'text': ' ', 'start': 0.4, 'end': 0.42},
        {'text': 'fell', 'start': 0.42, 'end': 0.8},
    ]
    result = normalize_words(raw)
    assert [w['word'] for w in result] == ['Rome', 'fell']


def test_chunk_words_into_cues_groups_by_chunk_size() -> None:
    words = [
        {'word': 'Rome', 'start': 0.0, 'end': 0.4},
        {'word': 'was', 'start': 0.4, 'end': 0.6},
        {'word': 'great', 'start': 0.6, 'end': 1.0},
        {'word': 'once', 'start': 1.0, 'end': 1.4},
        {'word': 'Then', 'start': 1.4, 'end': 1.6},
    ]
    cues = chunk_words_into_cues(words, chunk_size=4)
    assert len(cues) == 2
    assert cues[0] == {'start': 0.0, 'end': 1.4, 'text': 'Rome was great once'}
    assert cues[1] == {'start': 1.4, 'end': 1.6, 'text': 'Then'}


def test_fmt_srt_time_formats_hours_minutes_seconds_millis() -> None:
    assert fmt_srt_time(3725.123) == '01:02:05,123'


def test_fmt_srt_time_carries_rounding_overflow() -> None:
    assert fmt_srt_time(1.9996) == '00:00:02,000'


def test_build_srt_produces_numbered_blocks() -> None:
    cues = [
        {'start': 0.0, 'end': 1.4, 'text': 'Rome was great once'},
        {'start': 1.4, 'end': 1.6, 'text': 'Then'},
    ]
    srt = build_srt(cues).decode()
    assert srt == (
        '1\n00:00:00,000 --> 00:00:01,400\nRome was great once\n\n'
        '2\n00:00:01,400 --> 00:00:01,600\nThen'
    )
