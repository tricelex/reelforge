"""CaptionBundle stage — package subtitle + word-alignment assets.

Longform copies the ``alignment`` stage's SRT/ASS/word-timing data under
this stage's own execution so ``package_zip`` never has to reach back into
an unrelated stage's outputs. Clipping builds a full-video transcript SRT
plus one sliced SRT per approved candidate from the ``clip_transcribe``
manifest.
"""

import asyncio
import json
from typing import TYPE_CHECKING, Any, override

from server.apps.pipelines.logic.editor_handoff import (
    build_srt,
    is_clipping_run,
)
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)

if TYPE_CHECKING:
    from server.apps.clips.models import ClipCandidate

_MAX_WORDS = 200_000
_MAX_CANDIDATES = 500

_MIME_BY_SUFFIX: dict[str, str] = {
    '.srt': 'application/x-subrip',
    '.ass': 'text/x-ssa',
    '.json': 'application/json',
    '.txt': 'text/plain',
}


def _guess_mime(filename: str) -> str:
    """Return a MIME type for a caption bundle filename by extension."""
    for suffix, mime in _MIME_BY_SUFFIX.items():
        if filename.endswith(suffix):
            return mime
    return 'application/octet-stream'


async def _fetch_asset_bytes(asset_id: str) -> bytes:
    """Download bytes from an Asset by ID."""
    from server.apps.assets.models import Asset  # noqa: PLC0415

    asset = await Asset.objects.aget(id=asset_id)
    return await asyncio.to_thread(asset.file.read)


def _word_alignment_payload(
    scenes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten alignment scenes into a compact word-timing export."""
    assert len(scenes) <= _MAX_WORDS, 'scene count exceeded bound'  # noqa: S101
    return [
        {
            'scene_idx': scene.get('scene_idx'),
            'chapter_idx': scene.get('chapter_idx'),
            'start_s': scene.get('start_s'),
            'end_s': scene.get('end_s'),
            'words': scene.get('words', []),
        }
        for scene in scenes
    ]


async def _run_longform(ctx: StageContext) -> dict[str, bytes]:
    """Gather longform caption files as {filename: content}."""
    alignment = ctx.upstream.get('alignment', {})
    files: dict[str, bytes] = {}

    srt_asset_id = alignment.get('srt_asset_id')
    if srt_asset_id:
        files['captions.srt'] = await _fetch_asset_bytes(srt_asset_id)

    ass_asset_id = alignment.get('ass_asset_id')
    if ass_asset_id:
        files['captions.ass'] = await _fetch_asset_bytes(ass_asset_id)

    scenes = alignment.get('scenes', [])
    if scenes:
        files['word_alignment.json'] = json.dumps(
            _word_alignment_payload(scenes),
        ).encode()
    return files


async def _load_manifest(ctx: StageContext) -> dict[str, Any]:
    """Fetch and parse the clip_transcribe analysis manifest."""
    manifest_asset_id: str = ctx.upstream['clip_transcribe'][
        'manifest_asset_id'
    ]
    raw = await _fetch_asset_bytes(manifest_asset_id)
    manifest: dict[str, Any] = json.loads(raw)
    return manifest


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


def _words_in_range(
    words: list[dict[str, Any]],
    *,
    start_sec: float,
    end_sec: float,
) -> list[dict[str, Any]]:
    """Select and re-zero words whose window overlaps [start_sec, end_sec)."""
    assert end_sec > start_sec, (  # noqa: S101
        'end_sec must be greater than start_sec'
    )
    selected: list[dict[str, Any]] = []
    for i, word in enumerate(words):
        assert i < _MAX_WORDS, 'word index exceeded bound'  # noqa: S101
        w_start = float(word.get('start', 0.0))
        w_end = float(word.get('end', 0.0))
        if w_end <= start_sec or w_start >= end_sec:
            continue
        selected.append({
            **word,
            'start': max(0.0, w_start - start_sec),
            'end': max(0.0, w_end - start_sec),
        })
    return selected


async def _per_candidate_srt_bytes(
    ctx: StageContext,
    enriched_words: list[dict[str, Any]],
) -> dict[str, bytes]:
    """Build one sliced SRT per approved clip, keyed by candidate id."""
    from server.apps.pipelines.stages.clip_transcribe import (  # noqa: PLC0415
        _build_caption_segments,
    )

    candidates = await _load_approved_candidates(ctx)
    assert len(candidates) <= _MAX_CANDIDATES, (  # noqa: S101
        'candidate count exceeded bound'
    )
    by_candidate: dict[str, bytes] = {}
    for candidate in candidates:
        clip_words = _words_in_range(
            enriched_words,
            start_sec=candidate.start_sec,
            end_sec=candidate.end_sec,
        )
        segments = _build_caption_segments(clip_words)
        by_candidate[str(candidate.id)] = build_srt(segments)
    return by_candidate


async def _run_clipping(
    ctx: StageContext,
) -> tuple[dict[str, bytes], dict[str, bytes]]:
    """Gather clipping caption files: full transcript + per-candidate SRTs."""
    from server.apps.pipelines.stages.clip_transcribe import (  # noqa: PLC0415
        _build_caption_segments,
    )

    manifest = await _load_manifest(ctx)
    enriched_words: list[dict[str, Any]] = manifest.get(
        'enriched_transcript',
        [],
    )
    full_segments = _build_caption_segments(enriched_words)

    files: dict[str, bytes] = {
        'full_transcript.srt': build_srt(full_segments),
        'full_transcript.txt': str(
            manifest.get('transcript_text', ''),
        ).encode(),
        'word_alignment.json': json.dumps(enriched_words).encode(),
    }
    per_candidate = await _per_candidate_srt_bytes(ctx, enriched_words)
    return files, per_candidate


@register_stage
class CaptionBundleStage(Stage):
    """Terminal stage 3: subtitle + word-alignment asset bundle."""

    key = 'caption_bundle'
    queue = 'api'

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Save caption bundle files as SUBTITLE/DOC assets."""
        from server.apps.assets.models import AssetKind  # noqa: PLC0415

        clipping = is_clipping_run(ctx.upstream)
        per_candidate: dict[str, bytes] = {}
        if clipping:
            files, per_candidate = await _run_clipping(ctx)
        else:
            files = await _run_longform(ctx)

        output: dict[str, Any] = {
            'kind': 'clipping' if clipping else 'longform',
        }
        for filename, content in files.items():
            is_subtitle = filename.endswith(('.srt', '.ass'))
            asset = await ctx.assets.save(
                kind=AssetKind.SUBTITLE if is_subtitle else AssetKind.DOC,
                content=content,
                filename=filename,
                mime=_guess_mime(filename),
            )
            safe_key = filename.replace('.', '_')
            output[f'{safe_key}_asset_id'] = str(asset.id)

        candidate_srt_ids: dict[str, str] = {}
        for candidate_id, content in per_candidate.items():
            asset = await ctx.assets.save(
                kind=AssetKind.SUBTITLE,
                content=content,
                filename=f'{candidate_id}.srt',
                mime='application/x-subrip',
            )
            candidate_srt_ids[candidate_id] = str(asset.id)
        if candidate_srt_ids:
            output['per_candidate_srt_asset_ids'] = candidate_srt_ids
        return output
