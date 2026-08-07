"""Deterministic post-processing for LLM clip candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from server.apps.clips.logic.constants import (
    CLIP_BEAT_PLAYBACK_ORDER,
    CLIP_LENGTH_BOUNDS,
    MAX_COLD_OPEN_HOOK_SEC,
    ClipArrangement,
    ClipBeatRole,
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
#: Max note/label length stored on a beat.
_BEAT_TEXT_MAX = 500


@dataclass(frozen=True, slots=True)
class RankedBeat:
    """One Hook/Story/Payoff beat after snap + validation."""

    role: str
    start_sec: float
    end_sec: float
    label: str
    note: str

    def as_dict(self) -> dict[str, object]:
        """Serialize for ClipCandidate.beats JSONField."""
        return {
            'role': self.role,
            'start_sec': self.start_sec,
            'end_sec': self.end_sec,
            'label': self.label,
            'note': self.note,
        }


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
    beats: tuple[RankedBeat, ...]
    arrangement: str


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


def _playback_duration(beats: tuple[RankedBeat, ...]) -> float:
    total = 0.0
    max_beats = len(CLIP_BEAT_PLAYBACK_ORDER)
    for idx, beat in enumerate(beats):
        assert idx < max_beats  # noqa: S101
        total += beat.end_sec - beat.start_sec
    return total


def _synthesize_beats(start: float, end: float) -> tuple[RankedBeat, ...]:
    """Split an envelope into three contiguous Hook/Story/Payoff thirds."""
    assert end > start, 'envelope must be non-empty'  # noqa: S101
    span = end - start
    third = span / 3.0
    boundaries = (
        start,
        start + third,
        start + 2.0 * third,
        end,
    )
    beats: list[RankedBeat] = []
    for idx, role in enumerate(CLIP_BEAT_PLAYBACK_ORDER):
        assert idx < len(CLIP_BEAT_PLAYBACK_ORDER)  # noqa: S101
        beats.append(
            RankedBeat(
                role=role,
                start_sec=round(boundaries[idx], 3),
                end_sec=round(boundaries[idx + 1], 3),
                label='',
                note='',
            ),
        )
    return tuple(beats)


def _beat_attr(raw: object, key: str, default: object = '') -> object:
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(raw, key, default)


def _parse_raw_beats(clip: object) -> list[object] | None:
    raw = getattr(clip, 'beats', None)
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None
    return raw


def _normalize_beats(  # noqa: C901
    clip: object,
    *,
    envelope_start: float,
    envelope_end: float,
    word_starts: list[float],
    word_ends: list[float],
    scene_cuts: list[float],
    window_start: float,
    window_end: float,
    source_end: float,
) -> tuple[tuple[RankedBeat, ...], str] | None:
    """Snap and validate beats; synthesize contiguous thirds if missing."""
    arrangement_raw = str(
        getattr(clip, 'arrangement', ClipArrangement.CONTIGUOUS)
        or ClipArrangement.CONTIGUOUS,
    ).lower()
    if arrangement_raw not in ClipArrangement.values:
        arrangement_raw = ClipArrangement.CONTIGUOUS

    raw_beats = _parse_raw_beats(clip)
    if not raw_beats:
        return (
            _synthesize_beats(envelope_start, envelope_end),
            ClipArrangement.CONTIGUOUS,
        )

    if len(raw_beats) != len(CLIP_BEAT_PLAYBACK_ORDER):
        return None

    by_role: dict[str, RankedBeat] = {}
    max_raw = len(raw_beats)
    for idx in range(max_raw):
        assert idx < max_raw  # noqa: S101
        item = raw_beats[idx]
        role = str(_beat_attr(item, 'role', '')).lower().strip()
        if role not in ClipBeatRole.values:
            return None
        if role in by_role:
            return None
        start = float(_beat_attr(item, 'start_sec', 0) or 0)
        end = float(_beat_attr(item, 'end_sec', 0) or 0)
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
            return None
        label = str(_beat_attr(item, 'label', '') or '')[:_BEAT_TEXT_MAX]
        note = str(_beat_attr(item, 'note', '') or '')[:_BEAT_TEXT_MAX]
        by_role[role] = RankedBeat(
            role=role,
            start_sec=round(start, 3),
            end_sec=round(end, 3),
            label=label,
            note=note,
        )

    if set(by_role) != set(CLIP_BEAT_PLAYBACK_ORDER):
        return None

    ordered = tuple(by_role[role] for role in CLIP_BEAT_PLAYBACK_ORDER)
    hook, story, payoff = ordered
    if story.start_sec >= payoff.start_sec:
        return None
    if arrangement_raw == ClipArrangement.CONTIGUOUS:
        if not (
            hook.start_sec <= story.start_sec <= payoff.start_sec
        ):
            return None
        if hook.end_sec > story.end_sec + 1.0:
            return None
    else:
        hook_dur = hook.end_sec - hook.start_sec
        if hook_dur > MAX_COLD_OPEN_HOOK_SEC:
            return None
        # Cold open: hook teases a moment that story/payoff resolve.
        if hook.start_sec < story.start_sec and hook.end_sec <= story.start_sec:
            # Chronological cold-open is still contiguous-ish; keep cold_open
            # only when hook is out of chronological open position.
            arrangement_raw = ClipArrangement.CONTIGUOUS

    return ordered, arrangement_raw


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

        normalized = _normalize_beats(
            clip,
            envelope_start=start,
            envelope_end=end,
            word_starts=word_starts,
            word_ends=word_ends,
            scene_cuts=scene_cuts,
            window_start=window_start,
            window_end=window_end,
            source_end=source_end,
        )
        if normalized is None:
            continue
        beats, arrangement = normalized
        start = min(b.start_sec for b in beats)
        end = max(b.end_sec for b in beats)
        duration = _playback_duration(beats)
        if duration < min_dur or duration > max_dur:
            # Prefer clipping contiguous envelopes to bucket edges.
            if (
                arrangement == ClipArrangement.CONTIGUOUS
                and duration < min_dur
                and end + (min_dur - duration) <= window_end
            ):
                end = start + min_dur
                beats = _synthesize_beats(start, end)
                duration = _playback_duration(beats)
            elif (
                arrangement == ClipArrangement.CONTIGUOUS
                and duration > max_dur
            ):
                end = start + max_dur
                beats = _synthesize_beats(start, end)
                duration = _playback_duration(beats)
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
                beats=beats,
                arrangement=arrangement,
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
