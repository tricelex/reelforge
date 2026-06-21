"""Tests for transcript merge helpers."""

from server.apps.clips.logic.transcript_merge import (
    diarization_payload,
    merge_transcript_with_diarization,
)


def test_merge_assigns_speaker_by_overlap() -> None:
    enriched = [
        {'word': 'Hello', 'start': 0.0, 'end': 0.5, 'speaker_id': 'UNKNOWN'},
        {'word': 'there', 'start': 5.0, 'end': 5.5, 'speaker_id': 'UNKNOWN'},
    ]
    diarization = [
        {'speaker_id': 'SPEAKER_A', 'start': 0.0, 'end': 2.0},
        {'speaker_id': 'SPEAKER_B', 'start': 4.0, 'end': 8.0},
    ]
    result = merge_transcript_with_diarization(enriched, diarization)
    assert result[0]['speaker_id'] == 'SPEAKER_A'
    assert result[1]['speaker_id'] == 'SPEAKER_B'


def test_merge_keeps_unknown_when_no_overlap() -> None:
    enriched = [
        {'word': 'Hi', 'start': 10.0, 'end': 10.5, 'speaker_id': 'UNKNOWN'},
    ]
    diarization = [
        {'speaker_id': 'SPEAKER_A', 'start': 0.0, 'end': 2.0},
    ]
    result = merge_transcript_with_diarization(enriched, diarization)
    assert result[0]['speaker_id'] == 'UNKNOWN'


def test_merge_empty_diarization_passthrough() -> None:
    enriched = [
        {'word': 'Hi', 'start': 0.0, 'end': 0.5, 'speaker_id': 'UNKNOWN'},
    ]
    result = merge_transcript_with_diarization(enriched, [])
    assert result == enriched
    assert result is not enriched


def test_diarization_payload_wraps_segments() -> None:
    segments = [{'speaker_id': 'A', 'start': 0.0, 'end': 1.0}]
    assert diarization_payload(segments) == {'segments': segments}
