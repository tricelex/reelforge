"""Transcript + diarization merge helpers."""

from typing import Any

_UNKNOWN_SPEAKER = 'UNKNOWN'


def _overlap_seconds(
    word_start: float,
    word_end: float,
    seg_start: float,
    seg_end: float,
) -> float:
    overlap_start = max(word_start, seg_start)
    overlap_end = min(word_end, seg_end)
    if overlap_end <= overlap_start:
        return 0.0
    return overlap_end - overlap_start


def _speaker_for_word(
    word_start: float,
    word_end: float,
    diarization_segments: list[dict[str, Any]],
) -> str:
    best_speaker = _UNKNOWN_SPEAKER
    best_overlap = 0.0
    for segment in diarization_segments:
        seg_start = float(segment.get('start', 0))
        seg_end = float(segment.get('end', 0))
        overlap = _overlap_seconds(word_start, word_end, seg_start, seg_end)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = str(segment.get('speaker_id', _UNKNOWN_SPEAKER))
    return best_speaker


def merge_transcript_with_diarization(
    enriched_transcript: list[dict[str, Any]],
    diarization_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assign speaker_id to each word by temporal overlap with diarization."""
    if not diarization_segments:
        return [dict(word) for word in enriched_transcript]

    merged: list[dict[str, Any]] = []
    for word in enriched_transcript:
        start = float(word.get('start', 0))
        end = float(word.get('end', 0))
        merged.append(
            {
                'word': word.get('word', ''),
                'start': start,
                'end': end,
                'speaker_id': _speaker_for_word(
                    start,
                    end,
                    diarization_segments,
                ),
            },
        )
    return merged


def diarization_payload(segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap diarization segments for ClipAnalysisService."""
    return {'segments': segments}
