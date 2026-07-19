"""Deterministic post-processing for LLM clip candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from server.apps.clips.logic.constants import (
    CLIP_LENGTH_BOUNDS,
    ClipLengthBucket,
    compute_virality_score,
)

#: Max candidates accepted from one analysis pass.
_MAX_CANDIDATES = 50
#: Snap window around word/scene boundaries (seconds).
_SNAP_TOLERANCE_SEC = 1.25
#: Minimum overlap ratio that triggers suppression.
_OVERLAP_RATIO = 0.45
#: Default analysis window size for long transcripts.
WINDOW_SIZE_SEC = 20 * 60
WINDOW_OVERLAP_SEC = 2 * 60


@dataclass(frozen=True, slots=True)
class RankedClip:
    """Normalized clip candidate ready for persistence."""

    start_sec: float
    end_sec: float
    title: str
    hook_text: str
    caption_template: str
    headline: str
    reason: str
    hook_score: float
    flow_score: float
    value_score: float
    trend_score: float
    virality_score: float
    intent_match_score: float
    hook_reason: str
    flow_reason: str
    value_reason: str
    trend_reason: str
    confidence: float


def duration_bounds(
    bucket: str,
    *,
    custom_min_sec: float | None = None,
    custom_max_sec: float | None = None,
) -> tuple[float, float]:
    """Resolve inclusive duration bounds for a length bucket."""
    if bucket == ClipLengthBucket.CUSTOM:
        lo = float(custom_min_sec if custom_min_sec is not None else 15.0)
        hi = float(custom_max_sec if custom_max_sec is not None else 180.0)
        if lo > hi:
            lo, hi = hi, lo
        return max(5.0, lo), max(lo + 1.0, hi)
    return CLIP_LENGTH_BOUNDS.get(
        bucket,
        CLIP_LENGTH_BOUNDS[ClipLengthBucket.AUTO],
    )


def iter_transcript_windows(
    enriched_words: list[dict[str, Any]],
    *,
    video_duration: float | None,
    timeframe_start: float | None = None,
    timeframe_end: float | None = None,
    window_size_sec: float = WINDOW_SIZE_SEC,
    overlap_sec: float = WINDOW_OVERLAP_SEC,
) -> list[tuple[float, float]]:
    """Return overlapping analysis windows covering the selected timeframe."""
    assert window_size_sec > 0, 'window_size_sec must be positive'  # noqa: S101
    assert overlap_sec >= 0, 'overlap_sec must be non-negative'  # noqa: S101
    assert overlap_sec < window_size_sec, 'overlap must be smaller than window'  # noqa: S101

    start, end = _resolve_window_bounds(
        enriched_words,
        video_duration=video_duration,
        timeframe_start=timeframe_start,
        timeframe_end=timeframe_end,
    )
    if end <= start:
        return [(start, start)]

    step = window_size_sec - overlap_sec
    windows: list[tuple[float, float]] = []
    cursor = start
    max_windows = int((end - start) / step) + 3
    for _ in range(max_windows):
        if cursor >= end:
            break
        window_end = min(end, cursor + window_size_sec)
        windows.append((cursor, window_end))
        if window_end >= end:
            break
        cursor += step
    assert windows, 'expected at least one analysis window'  # noqa: S101
    return windows


def _resolve_window_bounds(
    enriched_words: list[dict[str, Any]],
    *,
    video_duration: float | None,
    timeframe_start: float | None,
    timeframe_end: float | None,
) -> tuple[float, float]:
    if video_duration is not None and video_duration > 0:
        end = float(video_duration)
    elif enriched_words:
        end = float(enriched_words[-1].get('end', 0.0))
    else:
        return 0.0, 0.0
    start = 0.0
    if timeframe_start is not None:
        start = max(0.0, float(timeframe_start))
    if timeframe_end is not None:
        end = min(end, float(timeframe_end))
    return start, end


def words_in_window(
    enriched_words: list[dict[str, Any]],
    start_sec: float,
    end_sec: float,
) -> list[dict[str, Any]]:
    """Return words overlapping ``[start_sec, end_sec]``."""
    result: list[dict[str, Any]] = []
    max_words = len(enriched_words)
    for idx, word in enumerate(enriched_words):
        assert idx < max_words  # noqa: S101
        w_start = float(word.get('start', 0))
        w_end = float(word.get('end', 0))
        if w_end < start_sec:
            continue
        if w_start > end_sec:
            break
        result.append(word)
    return result


def _clamp_score(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 2)


def _snap_boundary(
    value: float,
    *,
    word_times: list[float],
    scene_cuts: list[float],
    prefer: str,
) -> float:
    """Snap a boundary toward the nearest word or scene cut."""
    candidates = [
        t
        for t in (*word_times, *scene_cuts)
        if abs(t - value) <= _SNAP_TOLERANCE_SEC
    ]
    if not candidates:
        return value
    if prefer == 'start':
        earlier = [t for t in candidates if t <= value]
        return max(earlier) if earlier else min(candidates)
    later = [t for t in candidates if t >= value]
    return min(later) if later else max(candidates)


def _overlap_ratio(
    a_start: float,
    a_end: float,
    b_start: float,
    b_end: float,
) -> float:
    overlap = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    shorter = min(a_end - a_start, b_end - b_start)
    if shorter <= 0:
        return 0.0
    return overlap / shorter


def normalize_raw_clips(  # noqa: C901
    raw_clips: list[Any],
    *,
    enriched_words: list[dict[str, Any]],
    scene_cuts: list[float],
    video_duration: float | None,
    length_bucket: str = ClipLengthBucket.AUTO,
    custom_min_sec: float | None = None,
    custom_max_sec: float | None = None,
    clips_requested: int = 5,
    timeframe_start: float | None = None,
    timeframe_end: float | None = None,
) -> list[RankedClip]:
    """Validate, snap, score, dedupe, and rank raw LLM clip proposals."""
    assert clips_requested > 0, 'clips_requested must be positive'  # noqa: S101
    min_dur, max_dur = duration_bounds(
        length_bucket,
        custom_min_sec=custom_min_sec,
        custom_max_sec=custom_max_sec,
    )
    source_end = (
        float(video_duration)
        if video_duration is not None and video_duration > 0
        else (
            float(enriched_words[-1]['end'])
            if enriched_words
            else float('inf')
        )
    )
    window_start = float(timeframe_start or 0.0)
    window_end = float(
        timeframe_end if timeframe_end is not None else source_end,
    )
    word_starts = [float(w['start']) for w in enriched_words]
    word_ends = [float(w['end']) for w in enriched_words]

    ranked: list[RankedClip] = []
    max_raw = min(len(raw_clips), _MAX_CANDIDATES)
    for idx in range(max_raw):
        clip = raw_clips[idx]
        start = float(getattr(clip, 'start_sec', 0))
        end = float(getattr(clip, 'end_sec', 0))
        start = _snap_boundary(
            start,
            word_times=word_starts,
            scene_cuts=scene_cuts,
            prefer='start',
        )
        end = _snap_boundary(
            end,
            word_times=word_ends,
            scene_cuts=scene_cuts,
            prefer='end',
        )
        start = max(window_start, start)
        end = min(window_end, source_end, end)
        if end <= start:
            continue
        duration = end - start
        if duration < min_dur or duration > max_dur:
            # Prefer clipping to the nearest in-bucket edge when close.
            if duration < min_dur and end + (min_dur - duration) <= window_end:
                end = start + min_dur
                duration = end - start
            elif duration > max_dur:
                end = start + max_dur
                duration = end - start
            if duration < min_dur or duration > max_dur:
                continue

        hook = _clamp_score(getattr(clip, 'hook_score', 0))
        flow = _clamp_score(getattr(clip, 'flow_score', 0))
        value = _clamp_score(getattr(clip, 'value_score', 0))
        trend = _clamp_score(getattr(clip, 'trend_score', 0))
        intent = _clamp_score(getattr(clip, 'intent_match_score', 50))
        virality = compute_virality_score(
            hook_score=hook,
            flow_score=flow,
            value_score=value,
            trend_score=trend,
        )
        confidence = _clamp_score(
            (
                float(getattr(clip, 'confidence', 0))
                if getattr(clip, 'confidence', None) is not None
                else (hook + flow + value + trend) / 4.0
            ),
        )
        ranked.append(
            RankedClip(
                start_sec=round(start, 3),
                end_sec=round(end, 3),
                title=str(getattr(clip, 'title', 'Untitled clip'))[:200],
                hook_text=str(getattr(clip, 'hook_text', ''))[:200],
                caption_template=str(getattr(clip, 'caption_template', '')),
                headline=str(
                    getattr(clip, 'headline', '')
                    or getattr(clip, 'hook_text', ''),
                )[:200],
                reason=str(getattr(clip, 'reason', '')),
                hook_score=hook,
                flow_score=flow,
                value_score=value,
                trend_score=trend,
                virality_score=virality,
                intent_match_score=intent,
                hook_reason=str(getattr(clip, 'hook_reason', '')),
                flow_reason=str(getattr(clip, 'flow_reason', '')),
                value_reason=str(getattr(clip, 'value_reason', '')),
                trend_reason=str(getattr(clip, 'trend_reason', '')),
                confidence=confidence,
            ),
        )

    ranked.sort(key=lambda c: c.virality_score, reverse=True)
    selected: list[RankedClip] = []
    for clip in ranked:
        if len(selected) >= clips_requested:
            break
        overlaps = False
        for kept in selected:
            if (
                _overlap_ratio(
                    clip.start_sec,
                    clip.end_sec,
                    kept.start_sec,
                    kept.end_sec,
                )
                >= _OVERLAP_RATIO
            ):
                overlaps = True
                break
        if not overlaps:
            selected.append(clip)
    return selected
