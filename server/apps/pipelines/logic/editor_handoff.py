"""Helpers for editor-handoff (Resolve package) blueprints."""

from typing import Any

EDITOR_HANDOFF_BLUEPRINT_NAMES: frozenset[str] = frozenset({
    'longform_editor_v1',
    'longform_doc_editor_v1',
    'clipping_editor_v1',
    'clipping_editor_manual_v1',
    'longform_scene_export_v1',
})

HANDOFF_TAIL_START = 'editor_brief'

#: Stage keys that only appear in the clipping pipeline's upstream graph.
_CLIPPING_STAGE_KEYS = frozenset({
    'clip_ingest',
    'clip_transcribe',
    'clip_analyze',
    'clip_manual_setup',
    'clip_approval_gate',
})


def is_clipping_run(upstream: dict[str, Any]) -> bool:
    """Return True when the run's upstream outputs came from a clip pipeline.

    Handoff stages run identically for both pipeline kinds but must branch
    on which upstream stages actually populated ``ctx.upstream`` — this is
    cheaper and safer than an extra DB round trip to read
    ``run.blueprint.kind``.
    """
    assert isinstance(upstream, dict), 'upstream must be a dict'  # noqa: S101
    assert _CLIPPING_STAGE_KEYS, (  # noqa: S101
        'clipping stage key set must not be empty'
    )
    return any(key in upstream for key in _CLIPPING_STAGE_KEYS)


def is_editor_handoff_blueprint(
    name: str | None = None,
    *,
    snapshot: dict[str, Any] | None = None,
) -> bool:
    """Return True when the run uses an editor-package blueprint."""
    if name and name in EDITOR_HANDOFF_BLUEPRINT_NAMES:
        return True
    if name and '_editor_' in name:
        return True
    return bool(snapshot and snapshot.get('handoff') == 'editor_package')


def fmt_timecode(seconds: float, *, fps: float = 24.0) -> str:
    """Format seconds as HH:MM:SS:FF for CSV/EDL at ``fps``."""
    assert seconds >= 0, f'seconds must be >= 0, got {seconds}'  # noqa: S101
    assert fps > 0, f'fps must be > 0, got {fps}'  # noqa: S101
    total_frames = round(seconds * fps)
    frames_per_hour = int(fps * 3600)
    frames_per_min = int(fps * 60)
    hours, rem = divmod(total_frames, frames_per_hour)
    minutes, rem = divmod(rem, frames_per_min)
    secs, frames = divmod(rem, int(fps))
    return f'{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}'


def fmt_srt_time(seconds: float) -> str:
    """Format seconds as SRT HH:MM:SS,mmm."""
    total_ms = round(max(0.0, seconds) * 1000)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f'{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}'


def build_srt(segments: list[dict[str, Any]]) -> bytes:
    """Build SRT bytes from segments with start/end/text keys."""
    blocks: list[str] = []
    max_segments = 50_000
    for i, seg in enumerate(segments, start=1):
        assert i <= max_segments, 'SRT segment count exceeded bound'  # noqa: S101
        start = fmt_srt_time(float(seg['start']))
        end = fmt_srt_time(float(seg['end']))
        text = str(seg.get('text', '')).strip()
        if not text:
            continue
        blocks.append(f'{i}\n{start} --> {end}\n{text}')
    return '\n\n'.join(blocks).encode()


def build_edl_markers(
    events: list[dict[str, Any]],
    *,
    title: str,
    fps: float = 24.0,
) -> str:
    """Build a minimal CMX3600-style EDL from marker events.

    Each event needs ``name``, ``start_sec``, ``end_sec``.
    """
    lines = [f'TITLE: {title}', 'FCM: NON-DROP FRAME', '']
    max_events = 10_000
    for i, event in enumerate(events, start=1):
        assert i <= max_events, 'EDL event count exceeded bound'  # noqa: S101
        start = fmt_timecode(float(event['start_sec']), fps=fps)
        end = fmt_timecode(float(event['end_sec']), fps=fps)
        name = str(event.get('name', f'Event_{i}'))[:32]
        rec = f'{i:03d}  AX       V     C        '
        lines.extend((
            f'{rec}{start} {end} {start} {end}',
            f'* FROM CLIP NAME: {name}',
            '',
        ))
    return '\n'.join(lines)
