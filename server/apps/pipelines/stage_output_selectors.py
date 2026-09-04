"""Read-only selectors for per-stage output surfaces."""

import uuid
from collections.abc import Callable
from typing import Any, Final

from server.apps.pipelines.logic.value_objects import (
    RunAssetPayload,
    StageOutputPayload,
)
from server.apps.pipelines.models import (
    PipelineRun,
    StageExecution,
    StageStatus,
)
from server.apps.pipelines.run_asset_selectors import asset_to_payload
from server.common.storage import PresignUrlHelper

_BuildResult = tuple[str | None, str | None, dict[str, Any] | None]
_Builder = Callable[[str, StageExecution], _BuildResult]

# Requested stage keys the frontend may ask for that map onto a different
# real stage execution key in the backend.
_ALIASES: Final[dict[str, str]] = {
    'clip_detect': 'clip_analyze',
    'clip_score': 'clip_analyze',
    'clip_approval': 'clip_approval_gate',
}

_KNOWN_STAGE_KEYS: Final[frozenset[str]] = frozenset({
    'research',
    'outline',
    'script',
    'scene_breakdown',
    'narrative_qc',
    'visual_prompts',
    'visual_anchors',
    'image_gen',
    'motion',
    'tts',
    'alignment',
    'assembly',
    'qc',
    'publish',
    'thumbnail',
    'metadata',
    'cast_proposal',
    'script_gate',
    'storyboard_gate',
    'character_gate',
    'final_gate',
    'review_gate',
    'clip_ingest',
    'clip_transcribe',
    'clip_analyze',
    'clip_manual_setup',
    'clip_detect',
    'clip_score',
    'clip_render',
    'clip_approval',
    'clip_approval_gate',
    'clip_distribute',
    'footage_queries',
    'footage_search',
    'footage_prep',
    'editor_brief',
    'timeline_export',
    'caption_bundle',
    'clip_preview_render',
    'package_zip',
})


class StageNotFound(Exception):  # noqa: N818
    """Raised when a stage key is not a known pipeline stage."""


def _latest_attempt(run_id: str, stage_key: str) -> StageExecution | None:
    return (
        StageExecution.objects  # type: ignore[misc]
        .filter(run_id=run_id, stage_key=stage_key, parent=None)
        .order_by('-attempt')
        .first()
    )


def _latest_succeeded(run_id: str, stage_key: str) -> StageExecution | None:
    return (
        StageExecution.objects  # type: ignore[misc]
        .filter(
            run_id=run_id,
            stage_key=stage_key,
            parent=None,
            status=StageStatus.SUCCEEDED,
        )
        .order_by('-attempt')
        .first()
    )


def _resolve_source(
    run_id: str,
    real_key: str,
) -> tuple[str, StageExecution | None]:
    """Return the current status and the execution to render output from."""
    latest = _latest_attempt(run_id, real_key)
    if latest is None:
        return StageStatus.PENDING, None
    if latest.status == StageStatus.SUCCEEDED:
        return latest.status, latest
    return latest.status, _latest_succeeded(run_id, real_key)


def _build_research(_run_id: str, execution: StageExecution) -> _BuildResult:
    out = execution.output
    brief = out.get('brief', {})
    sources = out.get('sources', [])
    topic = brief.get('topic', '')
    lines = [f'# Research: {topic}', '', '## Key facts']
    lines.extend(f'- {fact}' for fact in brief.get('key_facts', []))
    lines.extend(['', '## Narrative angles'])
    lines.extend(f'- {angle}' for angle in brief.get('narrative_angles', []))
    summary = f'{topic} - {len(sources)} sources'
    return summary, '\n'.join(lines), None


def _build_outline(_run_id: str, execution: StageExecution) -> _BuildResult:
    chapters = execution.output.get('chapters', [])
    lines = [
        f'{ch.get("idx")}. {ch.get("title", "")} - {ch.get("thesis", "")}'
        for ch in chapters
    ]
    return f'{len(chapters)} chapters', '\n'.join(lines), None


def _build_script(_run_id: str, execution: StageExecution) -> _BuildResult:
    out = execution.output
    chapters = out.get('chapters', [])
    text = '\n\n'.join(ch.get('text', '') for ch in chapters)
    words = out.get('total_word_count', 0)
    return f'{words} words (~{words // 150} min)', text, None


def _build_scene_breakdown(
    _run_id: str,
    execution: StageExecution,
) -> _BuildResult:
    scenes = execution.output.get('scenes', [])
    data: dict[str, Any] = {
        'scenes': [
            {
                'index': scene.get('idx'),
                'heading': scene.get('beat', ''),
                'text': scene.get('narration_text', ''),
            }
            for scene in scenes
        ],
    }
    return f'{len(scenes)} scenes', None, data


def _build_visual_prompts(
    _run_id: str,
    execution: StageExecution,
) -> _BuildResult:
    prompts = execution.output.get('prompts', [])
    data: dict[str, Any] = {
        'prompts': [
            {
                'scene_index': prompt.get('scene_idx'),
                'prompt': prompt.get('prompt', ''),
                'negative_prompt': prompt.get('negative_prompt', ''),
            }
            for prompt in prompts
        ],
    }
    return f'{len(prompts)} prompts', None, data


def _build_footage_queries(
    _run_id: str,
    execution: StageExecution,
) -> _BuildResult:
    queries = execution.output.get('queries', [])
    data: dict[str, Any] = {
        'queries': [
            {
                'scene_index': query.get('scene_idx'),
                'primary_query': query.get('primary_query', ''),
                'fallback_queries': query.get('fallback_queries', []),
                'media_preference': query.get('media_preference', 'any'),
                'orientation': query.get('orientation', 'landscape'),
                'era_hint': query.get('era_hint', ''),
                'negative_terms': query.get('negative_terms', []),
                'ai_fallback_prompt': query.get('ai_fallback_prompt', ''),
            }
            for query in queries
        ],
    }
    return f'{len(queries)} queries', None, data


def _build_narrative_qc(
    _run_id: str,
    execution: StageExecution,
) -> _BuildResult:
    out = execution.output
    passed = bool(out.get('passed', False))
    score = out.get('score')
    issues = out.get('issues', [])
    data: dict[str, Any] = {
        'passed': passed,
        'score': score,
        'issues': issues,
    }
    if score is not None:
        summary = f'{"passed" if passed else "failed"} · score {score}'
    else:
        summary = 'passed' if passed else f'{len(issues)} issues'
    return summary, None, data


def _build_alignment(_run_id: str, execution: StageExecution) -> _BuildResult:
    scenes = execution.output.get('scenes', [])
    return f'{len(scenes)} aligned segments', None, {'scenes': scenes}


def _build_qc(_run_id: str, execution: StageExecution) -> _BuildResult:
    out = execution.output
    passed = bool(out.get('passed', False))
    failures = out.get('qc_report', {}).get('failures', [])
    checks = [
        {
            'name': str(failure.get('check', '')),
            'result': 'fail',
            'detail': str(failure.get('detail', '')),
        }
        for failure in failures
    ]
    data: dict[str, Any] = {'passed': passed, 'checks': checks}
    summary = 'QC passed' if passed else f'{len(failures)} QC failures'
    return summary, None, data


def _build_publish(run_id: str, execution: StageExecution) -> _BuildResult:
    video_id = execution.output.get('youtube_video_id')
    gate = _latest_succeeded(run_id, 'final_gate') or _latest_succeeded(
        run_id,
        'review_gate',
    )
    scheduled_at = gate.output.get('schedule_at') if gate is not None else None
    data: dict[str, Any] = {
        'status': 'COMPLETED' if video_id else 'PENDING',
        'watch_url': _watch_url(video_id) if video_id else None,
        'external_video_id': str(video_id) if video_id else None,
        'scheduled_at': scheduled_at,
    }
    summary = 'Published to YouTube' if video_id else None
    return summary, None, data


def _build_metadata(_run_id: str, execution: StageExecution) -> _BuildResult:
    out = execution.output
    data: dict[str, Any] = {
        'title': out.get('title', ''),
        'description': out.get('description', ''),
        'tags': out.get('tags', []),
        'made_for_kids': out.get('made_for_kids', False),
        'ai_disclosure': out.get('ai_disclosure', True),
    }
    return out.get('title'), None, data


def _build_gate(_run_id: str, execution: StageExecution) -> _BuildResult:
    return None, None, dict(execution.output)


def _read_asset_text(asset_id: str | None) -> str | None:
    """Return UTF-8 text from a pipeline Asset, or None if unavailable."""
    if not asset_id:
        return None
    from server.apps.assets.models import Asset  # noqa: PLC0415

    try:
        asset = Asset.objects.get(id=asset_id)
    except Asset.DoesNotExist:
        return None
    if not asset.file:
        return None
    try:
        with asset.file.open('rb') as handle:
            return handle.read().decode()
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _build_editor_brief(
    _run_id: str,
    execution: StageExecution,
) -> _BuildResult:
    """Render the LLM editorial brief for the stage output modal."""
    out = execution.output
    editorial = out.get('editorial')
    editorial_dict = editorial if isinstance(editorial, dict) else {}
    summary = str(
        editorial_dict.get('summary')
        or f'Editor brief ({out.get("kind", "unknown")})',
    )
    text = _read_asset_text(
        str(out['brief_asset_id']) if out.get('brief_asset_id') else None,
    )
    data: dict[str, Any] = {
        'kind': out.get('kind'),
        'brief_asset_id': out.get('brief_asset_id'),
        'editorial': editorial_dict or None,
    }
    return summary[:240], text, data


def _build_handoff_docs(
    _run_id: str,
    execution: StageExecution,
) -> _BuildResult:
    """Generic JSON+assets view for timeline/caption/package handoff stages."""
    out = dict(execution.output)
    summary = execution.stage_key.replace('_', ' ')
    if 'package_asset_id' in out:
        summary = 'Editor package ready'
    elif 'entry_count' in out:
        summary = f'Package ({out.get("entry_count")} entries)'
    return summary, None, out


def _build_clip_ingest(
    _run_id: str,
    execution: StageExecution,
) -> _BuildResult:
    out = execution.output
    width = out.get('source_width')
    resolution: str | None = None
    if width is not None:
        resolution = f'{width}x{out.get("source_height")}'
    data: dict[str, Any] = {
        'duration': out.get('source_duration_sec'),
        'resolution': resolution,
    }
    return out.get('source_title'), None, data


def _build_clip_transcribe(
    _run_id: str,
    execution: StageExecution,
) -> _BuildResult:
    return None, execution.output.get('transcript_text'), None


def _clip_candidates(run_id: str) -> list[Any]:
    from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

    return list(
        ClipCandidate.objects.filter(run_id=uuid.UUID(run_id)).order_by(
            'start_sec',
        ),
    )


def _build_clip_detect(run_id: str, _execution: StageExecution) -> _BuildResult:
    candidates = _clip_candidates(run_id)
    data: dict[str, Any] = {
        'candidates': [
            {
                'id': str(candidate.id),
                'start_s': candidate.start_sec,
                'end_s': candidate.end_sec,
                'reason': candidate.reason,
            }
            for candidate in candidates
        ],
    }
    return f'{len(candidates)} candidates', None, data


def _build_clip_score(run_id: str, _execution: StageExecution) -> _BuildResult:
    candidates = _clip_candidates(run_id)
    data: dict[str, Any] = {
        'candidates': [
            {
                'id': str(candidate.id),
                'score': candidate.relevance_score,
                'rationale': candidate.reason,
            }
            for candidate in candidates
        ],
    }
    return f'{len(candidates)} scored clips', None, data


def _build_empty(_run_id: str, _execution: StageExecution) -> _BuildResult:
    return None, None, None


_BUILDERS: Final[dict[str, _Builder]] = {
    'research': _build_research,
    'outline': _build_outline,
    'script': _build_script,
    'scene_breakdown': _build_scene_breakdown,
    'narrative_qc': _build_narrative_qc,
    'visual_prompts': _build_visual_prompts,
    'footage_queries': _build_footage_queries,
    'alignment': _build_alignment,
    'qc': _build_qc,
    'publish': _build_publish,
    'metadata': _build_metadata,
    'clip_ingest': _build_clip_ingest,
    'clip_transcribe': _build_clip_transcribe,
    'clip_analyze': _build_clip_detect,
    'clip_detect': _build_clip_detect,
    'clip_score': _build_clip_score,
    'script_gate': _build_gate,
    'storyboard_gate': _build_gate,
    'character_gate': _build_gate,
    'final_gate': _build_gate,
    'review_gate': _build_gate,
    'clip_approval': _build_gate,
    'clip_approval_gate': _build_gate,
    'editor_brief': _build_editor_brief,
    'timeline_export': _build_handoff_docs,
    'caption_bundle': _build_handoff_docs,
    'clip_preview_render': _build_handoff_docs,
    'package_zip': _build_handoff_docs,
}


def _watch_url(video_id: object) -> str:
    return f'https://www.youtube.com/watch?v={video_id}'


def _stage_assets(
    run_id: str,
    real_key: str,
    presign: PresignUrlHelper,
) -> list[RunAssetPayload]:
    from server.apps.assets.models import Asset  # noqa: PLC0415

    rows = (
        Asset.objects
        .filter(
            run_id=uuid.UUID(run_id),
            stage_execution__stage_key=real_key,
        )
        .select_related('stage_execution')
        .order_by('-created_at', '-id')
    )
    return [asset_to_payload(asset, presign) for asset in rows]


def _compute_kind(
    text: str | None,
    data: dict[str, Any] | None,
    assets: list[RunAssetPayload],
) -> str:
    channels = [bool(text), bool(data), bool(assets)]
    if sum(channels) > 1:
        return 'mixed'
    if assets:
        return 'media'
    if data:
        return 'json'
    return 'text'


def get_stage_output(
    run_id: str,
    stage_key: str,
    presign: PresignUrlHelper,
) -> StageOutputPayload:
    """Return the rendered output of one pipeline stage."""
    if not PipelineRun.objects.filter(id=uuid.UUID(run_id)).exists():
        raise PipelineRun.DoesNotExist
    if stage_key not in _KNOWN_STAGE_KEYS:
        raise StageNotFound(stage_key)

    real_key = _ALIASES.get(stage_key, stage_key)
    status, source = _resolve_source(run_id, real_key)

    summary: str | None = None
    text: str | None = None
    data: dict[str, Any] | None = None
    if source is not None:
        builder = _BUILDERS.get(stage_key, _build_empty)
        summary, text, data = builder(run_id, source)

    assets = _stage_assets(run_id, real_key, presign)
    return StageOutputPayload(
        stage_key=stage_key,
        status=status,
        kind=_compute_kind(text, data, assets),
        summary=summary,
        text=text,
        data=data,
        assets=assets,
    )
