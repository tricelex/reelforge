"""PackageZip stage — build and save the downloadable editor-handoff zip.

Gathers bytes from every upstream terminal stage (and, for longform runs,
the segment/source fan-out children) into a flat ``{path: bytes}`` mapping,
then delegates README/MANIFEST/zip assembly to
``server.apps.pipelines.services.package_builder``.
"""

import asyncio
import json
from typing import TYPE_CHECKING, Any, override

from server.apps.pipelines.logic.blueprint_profiles import (
    SEGMENT_STAGE,
    SOURCE_STAGE,
    resolve_role,
)
from server.apps.pipelines.logic.editor_handoff import is_clipping_run
from server.apps.pipelines.services import package_builder
from server.apps.pipelines.services.tts_shards import load_tts_chapter_shards
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)
from server.common.exceptions import FatalProviderError

if TYPE_CHECKING:
    from server.apps.assets.models import Asset

_MAX_ITEMS = 5000
_EXT_BY_MIME: dict[str, str] = {
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'video/mp4': 'mp4',
    'audio/mpeg': 'mp3',
    'audio/wav': 'wav',
}


def _ext_for_mime(mime: str) -> str:
    """Return a filename extension for a MIME type, defaulting to ``bin``."""
    return _EXT_BY_MIME.get(mime, 'bin')


async def _fetch_asset(asset_id: str) -> 'Asset':
    """Load an Asset row by ID."""
    from server.apps.assets.models import Asset  # noqa: PLC0415

    return await Asset.objects.aget(id=asset_id)


async def _fetch_asset_bytes(asset_id: str) -> bytes:
    """Download bytes from an Asset by ID."""
    asset = await _fetch_asset(asset_id)
    return await asyncio.to_thread(asset.file.read)


async def _build_role_asset_map(
    ctx: StageContext,
    role: str,
) -> dict[int, str]:
    """Return {scene_idx: asset_id} from the run's ``role`` stage children."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    stage_key = resolve_role(ctx.run.blueprint_snapshot or {}, role)
    asset_map: dict[int, str] = {}
    async for child in StageExecution.objects.filter(
        run=ctx.run,
        stage_key=stage_key,
        parent__isnull=False,
        status=StageStatus.SUCCEEDED,
    ).order_by('shard_index'):
        output = child.output
        scene_idx = output.get('scene_idx')
        asset_id = output.get('asset_id')
        if scene_idx is not None and asset_id:
            asset_map[int(scene_idx)] = str(asset_id)
    return asset_map


async def _copy_by_field_map(
    output: dict[str, Any],
    field_to_path: dict[str, str],
) -> dict[str, bytes]:
    """Fetch asset bytes for each populated field, keyed by target path."""
    files: dict[str, bytes] = {}
    for field, path in field_to_path.items():
        asset_id = output.get(field)
        if asset_id:
            files[path] = await _fetch_asset_bytes(asset_id)
    return files


def _script_markdown(script: dict[str, Any]) -> str:
    """Render script chapters as a simple markdown document."""
    lines: list[str] = ['# Script', '']
    for ch in script.get('chapters', []):
        title = f'## Chapter {ch.get("idx", "?")}: {ch.get("title", "")}'
        lines.extend((
            title,
            '',
            str(ch.get('text', '')).strip(),
            '',
        ))
    return '\n'.join(lines)


def _outline_markdown(outline: dict[str, Any]) -> str:
    """Render outline chapters as a simple markdown bullet list."""
    lines: list[str] = ['# Outline', '']
    for ch in outline.get('chapters', []):
        title = ch.get('title', '')
        device = ch.get('retention_device', '')
        lines.append(f'- **{title}** — {device}')
    return '\n'.join(lines)


def _title_block(meta: dict[str, Any]) -> list[str]:
    """Render the Title section: primary title plus optional backups."""
    lines: list[str] = [
        '## Title',
        '',
        '**Primary:**',
        '```',
        str(meta.get('title', '')),
        '```',
    ]
    alternates = meta.get('title_alternates') or []
    if alternates:
        lines.extend(('', '**Backups:**'))
        for alt in alternates:
            lines.extend(('```', str(alt), '```'))
    return lines


def _thumbnail_block(meta: dict[str, Any]) -> list[str]:
    """Render the optional Thumbnail note section, or nothing."""
    thumbnail_text = str(meta.get('thumbnail_text', '')).strip()
    thumbnail_notes = str(meta.get('thumbnail_notes', '')).strip()
    if not thumbnail_text and not thumbnail_notes:
        return []
    lines: list[str] = ['', '---', '', '## Thumbnail note', '']
    if thumbnail_notes:
        lines.append(thumbnail_notes)
    if thumbnail_text:
        lines.append(f'\nSuggested overlay text: **"{thumbnail_text}"**')
    return lines


def _brand_checklist_block(meta: dict[str, Any]) -> list[str]:
    """Render the optional Brand-contract check section, or nothing."""
    checklist = meta.get('brand_checklist') or []
    if not checklist:
        return []
    lines: list[str] = ['', '---', '', '## Brand-contract check', '']
    lines.extend(f'- {item}' for item in checklist)
    return lines


def _publish_metadata_markdown(topic: str, meta: dict[str, Any]) -> str:
    """Render the metadata stage's output as a publish-ready doc.

    Mirrors a hand-written publish brief: primary title (+ backups),
    paste-ready description, tags, category, thumbnail guidance, and a
    brand-contract checklist — each optional section only appears when
    the stage populated it.
    """
    lines: list[str] = [
        '# Publish Metadata — YouTube',
        '',
        f'**Topic:** {topic}',
        '',
        '---',
        '',
        *_title_block(meta),
        '',
        '---',
        '',
        '## Description',
        '',
        '```',
        str(meta.get('description', '')),
        '```',
        '',
        '---',
        '',
        '## Tags',
        '',
        '```',
        ', '.join(meta.get('tags') or []),
        '```',
        '',
        '---',
        '',
        '## Other publish fields',
        '',
        '| Field | Value |',
        '|---|---|',
        f'| Category | {meta.get("category", "Education")} |',
        *_thumbnail_block(meta),
        *_brand_checklist_block(meta),
    ]
    return '\n'.join(lines)


async def _gather_longform_docs(ctx: StageContext) -> dict[str, bytes]:
    """Gather docs/: EDIT_BRIEF.md, script.md, outline.md?, composition."""
    brief_id = ctx.upstream.get('editor_brief', {}).get('brief_asset_id')
    if not brief_id:
        raise FatalProviderError(
            'editor_brief must produce a brief before package_zip runs',
            provider='***REMOVED***',
        )
    metadata = ctx.upstream.get('metadata', {})
    files: dict[str, bytes] = {
        'docs/EDIT_BRIEF.md': await _fetch_asset_bytes(brief_id),
        'docs/metadata.json': json.dumps({
            **metadata,
            'topic': ctx.run.topic,
            'run_id': str(ctx.run.id),
        }).encode(),
    }
    if metadata:
        files['docs/PUBLISH_METADATA.md'] = _publish_metadata_markdown(
            str(ctx.run.topic),
            metadata,
        ).encode()
    script = ctx.upstream.get('script', {})
    if script:
        files['docs/script.md'] = _script_markdown(script).encode()
        files['docs/scene_composition.json'] = json.dumps(
            ctx.upstream.get('scene_breakdown', {}),
        ).encode()
    outline = ctx.upstream.get('outline', {})
    if outline:
        files['docs/outline.md'] = _outline_markdown(outline).encode()
    return files


async def _gather_vo(ctx: StageContext) -> dict[str, bytes]:
    """Gather audio/vo/ch_NNN.mp3 from succeeded TTS chapter shards."""
    files: dict[str, bytes] = {}
    shards = await load_tts_chapter_shards(ctx.run)
    assert len(shards) <= _MAX_ITEMS, (  # noqa: S101
        'tts shard count exceeded bound'
    )
    for shard in shards:
        content = await _fetch_asset_bytes(shard['asset_id'])
        files[f'audio/vo/ch_{shard["chapter_idx"]:03d}.mp3'] = content
    return files


async def _gather_video_scenes(ctx: StageContext) -> dict[str, bytes]:
    """Gather video/scenes/sc_NNNN.mp4 from motion/footage_prep children."""
    scene_map = await _build_role_asset_map(ctx, SEGMENT_STAGE)
    assert len(scene_map) <= _MAX_ITEMS, (  # noqa: S101
        'scene count exceeded bound'
    )
    files: dict[str, bytes] = {}
    for scene_idx, asset_id in scene_map.items():
        content = await _fetch_asset_bytes(asset_id)
        files[f'video/scenes/sc_{scene_idx:04d}.mp4'] = content
    return files


async def _gather_stills(ctx: StageContext) -> dict[str, bytes]:
    """Gather stills/scenes/sc_NNNN.* from image_gen/footage_search sources."""
    still_map = await _build_role_asset_map(ctx, SOURCE_STAGE)
    assert len(still_map) <= _MAX_ITEMS, (  # noqa: S101
        'still count exceeded bound'
    )
    files: dict[str, bytes] = {}
    for scene_idx, asset_id in still_map.items():
        asset = await _fetch_asset(asset_id)
        ext = _ext_for_mime(asset.mime)
        content = await asyncio.to_thread(asset.file.read)
        files[f'stills/scenes/sc_{scene_idx:04d}.{ext}'] = content
    return files


async def _gather_longform_captions(ctx: StageContext) -> dict[str, bytes]:
    """Gather captions/ from the caption_bundle stage's longform output."""
    return await _copy_by_field_map(
        ctx.upstream.get('caption_bundle', {}),
        {
            'captions_srt_asset_id': 'captions/captions.srt',
            'captions_ass_asset_id': 'captions/captions.ass',
            'word_alignment_json_asset_id': 'captions/word_alignment.json',
        },
    )


async def _gather_timeline(ctx: StageContext) -> dict[str, bytes]:
    """Gather timeline/ from the timeline_export stage's longform output."""
    return await _copy_by_field_map(
        ctx.upstream.get('timeline_export', {}),
        {
            'markers_csv_asset_id': 'timeline/markers.csv',
            'shot_list_csv_asset_id': 'timeline/shot_list.csv',
            'markers_edl_asset_id': 'timeline/markers.edl',
        },
    )


async def _gather_thumbnails(ctx: StageContext) -> dict[str, bytes]:
    """Gather thumbnails/, if a thumbnail stage ran upstream."""
    candidates = ctx.upstream.get('thumbnail', {}).get('candidates', [])
    assert len(candidates) <= _MAX_ITEMS, (  # noqa: S101
        'thumbnail count exceeded bound'
    )
    files: dict[str, bytes] = {}
    for candidate in candidates:
        asset_id = candidate.get('asset_id')
        if not asset_id:
            continue
        rank = int(candidate.get('rank', 0))
        files[f'thumbnails/thumb_{rank:02d}.jpg'] = await _fetch_asset_bytes(
            asset_id,
        )
    return files


async def _gather_longform_files(ctx: StageContext) -> dict[str, bytes]:
    """Assemble the full longform editor package file tree."""
    files: dict[str, bytes] = {}
    files.update(await _gather_longform_docs(ctx))
    files.update(await _gather_vo(ctx))
    files.update(await _gather_video_scenes(ctx))
    files.update(await _gather_stills(ctx))
    files.update(await _gather_longform_captions(ctx))
    files.update(await _gather_timeline(ctx))
    files.update(await _gather_thumbnails(ctx))
    return files


async def _gather_clipping_docs(ctx: StageContext) -> dict[str, bytes]:
    """Gather docs/: EDIT_BRIEF.md and scene_cuts.json, if available."""
    brief_id = ctx.upstream.get('editor_brief', {}).get('brief_asset_id')
    if not brief_id:
        raise FatalProviderError(
            'editor_brief must produce a brief before package_zip runs',
            provider='***REMOVED***',
        )
    files: dict[str, bytes] = {
        'docs/EDIT_BRIEF.md': await _fetch_asset_bytes(brief_id),
    }
    scene_cuts = ctx.upstream.get('clip_transcribe', {}).get('scene_cuts')
    if scene_cuts:
        files['docs/scene_cuts.json'] = json.dumps(scene_cuts).encode()
    return files


async def _gather_candidates(ctx: StageContext) -> dict[str, bytes]:
    """Gather candidates/ from the timeline_export stage's clipping output."""
    return await _copy_by_field_map(
        ctx.upstream.get('timeline_export', {}),
        {
            'candidates_json_asset_id': 'candidates/candidates.json',
            'candidates_csv_asset_id': 'candidates/candidates.csv',
            'markers_edl_asset_id': 'candidates/markers.edl',
        },
    )


async def _gather_clipping_captions(ctx: StageContext) -> dict[str, bytes]:
    """Gather captions/ from the caption_bundle stage's clipping output."""
    cb = ctx.upstream.get('caption_bundle', {})
    files = await _copy_by_field_map(
        cb,
        {
            'full_transcript_srt_asset_id': 'captions/full_transcript.srt',
            'full_transcript_txt_asset_id': 'captions/full_transcript.txt',
            'word_alignment_json_asset_id': 'captions/word_alignment.json',
        },
    )
    per_candidate: dict[str, str] = cb.get('per_candidate_srt_asset_ids', {})
    assert len(per_candidate) <= _MAX_ITEMS, (  # noqa: S101
        'candidate count exceeded bound'
    )
    for candidate_id, asset_id in per_candidate.items():
        path = f'captions/per_candidate/{candidate_id}.srt'
        files[path] = await _fetch_asset_bytes(asset_id)
    return files


async def _gather_clipping_files(ctx: StageContext) -> dict[str, bytes]:
    """Assemble the full clipping editor package file tree."""
    files: dict[str, bytes] = {}
    files.update(await _gather_clipping_docs(ctx))
    files.update(await _gather_candidates(ctx))
    files.update(await _gather_clipping_captions(ctx))
    return files


@register_stage
class PackageZipStage(Stage):
    """Terminal stage (final): zip the editor package and save it."""

    key = 'package_zip'
    queue = 'render'
    timeout_s = 3600

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Build the editor package zip and save it as a PACKAGE asset."""
        from server.apps.assets.models import AssetKind  # noqa: PLC0415

        clipping = is_clipping_run(ctx.upstream)
        files = (
            await _gather_clipping_files(ctx)
            if clipping
            else await _gather_longform_files(ctx)
        )
        assert files, 'package must contain at least one file'  # noqa: S101

        run_id = str(ctx.run.id)
        root_name = package_builder.package_root_name(
            run_id,
            is_clipping=clipping,
        )
        source_asset_ids = package_builder.collect_source_asset_ids(
            ctx.upstream,
        )
        files['README.md'] = package_builder.build_readme(
            is_clipping=clipping,
        )
        files['MANIFEST.json'] = package_builder.build_manifest(
            files,
            source_asset_ids=source_asset_ids,
            root_name=root_name,
        )

        zip_bytes = package_builder.build_zip(files, root_name=root_name)
        asset = await ctx.assets.save(
            kind=AssetKind.PACKAGE,
            content=zip_bytes,
            filename=f'{root_name}.zip',
            mime='application/zip',
        )
        return {
            'package_asset_id': str(asset.id),
            'size_bytes': len(zip_bytes),
            'entry_count': len(files),
            'root_name': root_name,
        }
