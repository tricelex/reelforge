"""TimelineExport stage — markers.csv / shot_list.csv / markers.edl / EDL.

Longform sources timing from ``alignment`` scenes when present, falling
back to ``scene_breakdown`` scenes with estimated cumulative timing.
Clipping exports the approved ``ClipCandidate`` rows instead.
"""

import csv
import io
import json
from typing import TYPE_CHECKING, Any, override

from server.apps.pipelines.logic.editor_handoff import (
    build_edl_markers,
    fmt_timecode,
    is_clipping_run,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)

if TYPE_CHECKING:
    from server.apps.clips.models import ClipCandidate

_MAX_ROWS = 5000
_DEFAULT_FPS = 24.0


def _guess_mime(filename: str) -> str:
    """Return the MIME type for a timeline export filename by extension."""
    if filename.endswith('.csv'):
        return 'text/csv'
    if filename.endswith('.json'):
        return 'application/json'
    return 'text/plain'


def _write_csv(header: list[str], rows: list[list[str]]) -> bytes:
    """Write rows to CSV bytes with the given header."""
    assert header, 'header must be non-empty'  # noqa: S101
    assert len(rows) <= _MAX_ROWS, (  # noqa: S101
        'CSV row count exceeded bound'
    )
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\n')
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode()


def _estimated_scene_windows(
    scenes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fabricate start_s/end_s for scene_breakdown scenes via est_seconds.

    Used only when ``alignment`` has not run yet (or was skipped) so the
    editor package still ships a usable, if approximate, timeline.
    """
    ordered = sorted(scenes, key=lambda s: int(s['idx']))
    windows: list[dict[str, Any]] = []
    cursor = 0.0
    for i, scene in enumerate(ordered):
        assert i < _MAX_ROWS, 'scene index exceeded bound'  # noqa: S101
        duration = float(scene.get('est_seconds', 8.0))
        windows.append({
            **scene,
            'scene_idx': int(scene['idx']),
            'start_s': cursor,
            'end_s': cursor + duration,
        })
        cursor += duration
    return windows


def _resolve_scene_windows(ctx: StageContext) -> list[dict[str, Any]]:
    """Prefer alignment scene timing; fall back to estimated windows."""
    aligned = ctx.upstream.get('alignment', {}).get('scenes', [])
    if isinstance(aligned, list) and aligned:
        return [s for s in aligned if isinstance(s, dict)]
    breakdown_scenes = ctx.upstream.get('scene_breakdown', {}).get(
        'scenes',
        [],
    )
    scenes = breakdown_scenes if isinstance(breakdown_scenes, list) else []
    return _estimated_scene_windows(
        [s for s in scenes if isinstance(s, dict)],
    )


def _scene_breakdown_map(ctx: StageContext) -> dict[int, dict[str, Any]]:
    """Index scene_breakdown scenes by idx for shot_list detail lookups."""
    scenes = ctx.upstream.get('scene_breakdown', {}).get('scenes', [])
    return {int(s['idx']): s for s in scenes}


def _markers_csv_rows(
    scenes: list[dict[str, Any]],
    *,
    fps: float,
) -> list[list[str]]:
    """Build markers.csv data rows from resolved scene windows."""
    rows: list[list[str]] = []
    for i, scene in enumerate(scenes):
        assert i < _MAX_ROWS, (  # noqa: S101
            'marker row count exceeded bound'
        )
        start_s = float(scene['start_s'])
        end_s = float(scene['end_s'])
        name = f'Scene {scene.get("scene_idx", i)}'
        notes = str(scene.get('text', scene.get('beat', ''))).strip()[:200]
        rows.append([
            name,
            fmt_timecode(start_s, fps=fps),
            fmt_timecode(end_s, fps=fps),
            f'{start_s:.3f}',
            f'{end_s:.3f}',
            notes,
        ])
    return rows


def _shot_list_rows(
    scenes: list[dict[str, Any]],
    breakdown_map: dict[int, dict[str, Any]],
) -> list[list[str]]:
    """Build shot_list.csv data rows joining timing with scene detail."""
    rows: list[list[str]] = []
    for i, scene in enumerate(scenes):
        assert i < _MAX_ROWS, (  # noqa: S101
            'shot list row count exceeded bound'
        )
        scene_idx = int(scene.get('scene_idx', i))
        detail = breakdown_map.get(scene_idx, {})
        start_s = float(scene['start_s'])
        end_s = float(scene['end_s'])
        rows.append([
            str(scene_idx),
            str(detail.get('chapter_idx', scene.get('chapter_idx', ''))),
            f'{start_s:.3f}',
            f'{end_s:.3f}',
            f'{end_s - start_s:.3f}',
            str(detail.get('shot_type', '')),
            str(detail.get('visual_concept', '')),
            str(detail.get('narration_text', scene.get('text', ''))),
        ])
    return rows


def _build_longform_files(ctx: StageContext) -> dict[str, bytes]:
    """Build markers.csv, shot_list.csv, and markers.edl for a longform run."""
    scenes = _resolve_scene_windows(ctx)
    breakdown_map = _scene_breakdown_map(ctx)

    markers_csv = _write_csv(
        [
            'name',
            'start_timecode',
            'end_timecode',
            'start_sec',
            'end_sec',
            'notes',
        ],
        _markers_csv_rows(scenes, fps=_DEFAULT_FPS),
    )
    shot_list_csv = _write_csv(
        [
            'scene_idx',
            'chapter_idx',
            'start_sec',
            'end_sec',
            'duration_sec',
            'shot_type',
            'visual_concept',
            'narration_text',
        ],
        _shot_list_rows(scenes, breakdown_map),
    )
    events = [
        {
            'name': f'Scene {s.get("scene_idx", i)}',
            'start_sec': s['start_s'],
            'end_sec': s['end_s'],
        }
        for i, s in enumerate(scenes)
    ]
    edl = build_edl_markers(events, title=ctx.run.topic, fps=_DEFAULT_FPS)
    return {
        'markers.csv': markers_csv,
        'shot_list.csv': shot_list_csv,
        'markers.edl': edl.encode(),
    }


async def _load_approved_candidates(
    ctx: StageContext,
) -> list['ClipCandidate']:
    """Fetch approved ClipCandidate rows ordered by start time."""
    from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

    approved_ids: list[str] = ctx.upstream.get(
        'clip_approval_gate',
        {},
    ).get('approved_candidate_ids', [])
    if not approved_ids:
        return []
    return [
        c
        async for c in ClipCandidate.objects.filter(
            id__in=approved_ids,
        ).order_by('start_sec')
    ]


def _candidate_dict(candidate: 'ClipCandidate') -> dict[str, Any]:
    """Serialize one candidate to a plain dict for JSON/CSV export."""
    return {
        'id': str(candidate.id),
        'title': candidate.title,
        'hook_text': candidate.hook_text,
        'start_sec': candidate.start_sec,
        'end_sec': candidate.end_sec,
        'duration_sec': candidate.duration_sec,
        'status': candidate.status,
        'relevance_score': candidate.relevance_score,
        'virality_score': candidate.virality_score,
        'hook_score': candidate.hook_score,
        'arrangement': getattr(candidate, 'arrangement', '') or 'contiguous',
        'beats': getattr(candidate, 'beats', None) or [],
    }


async def _build_clipping_files(ctx: StageContext) -> dict[str, bytes]:
    """Build candidates.json, candidates.csv, and markers.edl for clipping."""
    candidates = await _load_approved_candidates(ctx)
    dicts = [_candidate_dict(c) for c in candidates]

    candidates_json = json.dumps(dicts, indent=2).encode()
    candidates_csv = _write_csv(
        [
            'id',
            'title',
            'start_sec',
            'end_sec',
            'duration_sec',
            'hook_text',
            'arrangement',
            'relevance_score',
            'virality_score',
            'status',
        ],
        [
            [
                d['id'],
                d['title'],
                f'{d["start_sec"]:.3f}',
                f'{d["end_sec"]:.3f}',
                f'{d["duration_sec"]:.3f}',
                d['hook_text'],
                d['arrangement'],
                f'{d["relevance_score"]:.3f}',
                f'{d["virality_score"]:.3f}',
                d['status'],
            ]
            for d in dicts
        ],
    )
    events: list[dict[str, Any]] = []
    max_candidates = len(dicts)
    for c_idx, d in enumerate(dicts):
        assert c_idx < max_candidates  # noqa: S101
        beats = d.get('beats') or []
        if isinstance(beats, list) and beats:
            max_beats = 3
            for b_idx, beat in enumerate(beats[:max_beats]):
                assert b_idx < max_beats  # noqa: S101
                if not isinstance(beat, dict):
                    continue
                role = str(beat.get('role', 'beat')).upper()
                events.append({
                    'name': f'{d["title"]} — {role}',
                    'start_sec': float(beat.get('start_sec', 0) or 0),
                    'end_sec': float(beat.get('end_sec', 0) or 0),
                })
        else:
            events.append({
                'name': d['title'],
                'start_sec': d['start_sec'],
                'end_sec': d['end_sec'],
            })
    edl = build_edl_markers(events, title=ctx.run.topic, fps=_DEFAULT_FPS)
    return {
        'candidates.json': candidates_json,
        'candidates.csv': candidates_csv,
        'markers.edl': edl.encode(),
    }


@register_stage
class TimelineExportStage(Stage):
    """Terminal stage 2: markers/shot-list/EDL export."""

    key = 'timeline_export'
    queue = 'api'

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Build timeline export files and save them as DOC assets."""
        from server.apps.assets.models import AssetKind  # noqa: PLC0415

        clipping = is_clipping_run(ctx.upstream)
        files = (
            await _build_clipping_files(ctx)
            if clipping
            else _build_longform_files(ctx)
        )
        assert files, (  # noqa: S101
            'timeline export must produce at least one file'
        )

        output: dict[str, Any] = {
            'kind': 'clipping' if clipping else 'longform',
        }
        for filename, content in files.items():
            asset = await ctx.assets.save(
                kind=AssetKind.DOC,
                content=content,
                filename=filename,
                mime=_guess_mime(filename),
            )
            key = filename.replace('.', '_') + '_asset_id'
            output[key] = str(asset.id)
        return output
