"""Assembly stage — combine motion + TTS + music + subtitles → final video."""

import asyncio
import operator
import tempfile
from pathlib import Path
from typing import Any, ClassVar, override

from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


def _group_scenes_by_chapter(
    scenes: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    """Group alignment scene dicts by chapter_idx, preserving sorted order."""
    groups: dict[int, list[dict[str, Any]]] = {}
    for scene in scenes:
        ch = scene['chapter_idx']
        groups.setdefault(ch, []).append(scene)
    return dict(sorted(groups.items()))


def _build_music_map(
    entries: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Index music_plan entries by chapter_idx."""
    return {e['chapter_idx']: e for e in entries}


async def _build_scene_asset_map(ctx: StageContext) -> dict[int, str]:
    """Return {scene_idx: asset_id} from motion stage child executions in DB."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    scene_map: dict[int, str] = {}
    async for child in StageExecution.objects.filter(
        run=ctx.run,
        stage_key='motion',
        parent__isnull=False,
        status=StageStatus.SUCCEEDED,
    ).order_by('shard_index'):
        output = child.output
        scene_idx = output.get('scene_idx')
        asset_id = output.get('asset_id')
        if scene_idx is not None and asset_id:
            scene_map[int(scene_idx)] = str(asset_id)
    return scene_map


async def _build_chapter_audio_map(ctx: StageContext) -> dict[int, str]:
    """Return {chapter_idx: asset_id} from tts stage child executions in DB."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    chapter_map: dict[int, str] = {}
    async for child in StageExecution.objects.filter(
        run=ctx.run,
        stage_key='tts',
        parent__isnull=False,
        status=StageStatus.SUCCEEDED,
    ).order_by('shard_index'):
        output = child.output
        ch_idx = output.get('chapter_idx')
        asset_id = output.get('asset_id')
        if ch_idx is not None and asset_id:
            chapter_map[int(ch_idx)] = str(asset_id)
    return chapter_map


async def _fetch_asset_bytes(asset_id: str) -> bytes:
    """Download bytes from a pipeline Asset by ID."""
    from server.apps.assets.models import Asset  # noqa: PLC0415

    asset = await Asset.objects.aget(id=asset_id)
    return await asyncio.to_thread(asset.file.read)


async def _fetch_library_bytes(library_asset_id: str) -> bytes:
    """Download bytes from a LibraryAsset by ID."""
    from server.apps.assets.models import LibraryAsset  # noqa: PLC0415

    asset = await LibraryAsset.objects.aget(id=library_asset_id)
    return await asyncio.to_thread(asset.file.read)


def _resolve_watermark_config(
    ctx: StageContext,
) -> tuple[str | None, float]:
    """Return (watermark_asset_id, opacity) from channel branding."""
    branding = getattr(ctx.channel, 'branding', None)
    watermark_asset_id: str | None = None
    watermark_opacity = 0.6
    if branding:
        wm = getattr(branding, 'watermark', None)
        if wm:
            watermark_asset_id = str(wm.id)
        watermark_opacity = float(getattr(branding, 'watermark_opacity', 0.6))
    return watermark_asset_id, watermark_opacity


async def _write_chapter_audio_files(
    tmp: Path,
    chapter_audio_map: dict[int, str],
) -> dict[int, str]:
    """Download chapter TTS assets into tmp; return {idx: path}."""
    chapter_audio_files: dict[int, str] = {}
    for ch_idx, audio_asset_id in chapter_audio_map.items():
        audio_bytes = await _fetch_asset_bytes(audio_asset_id)
        audio_file = tmp / f'ch_{ch_idx:03d}.mp3'
        await asyncio.to_thread(audio_file.write_bytes, audio_bytes)
        chapter_audio_files[ch_idx] = str(audio_file)
    return chapter_audio_files


async def _build_chapter_files(
    tmp: Path,
    scene_groups: dict[int, list[dict[str, Any]]],
    scene_asset_map: dict[int, str],
    chapter_audio_files: dict[int, str],
) -> list[str]:
    """Mux scenes per chapter and concat; return ordered chapter file paths."""
    from server.apps.rendering import ffmpeg  # noqa: PLC0415

    chapter_files: list[str] = []
    for ch_idx, ch_scenes in scene_groups.items():
        scene_mezz_files: list[str] = []
        audio_path = chapter_audio_files.get(ch_idx, '')
        for scene in sorted(ch_scenes, key=operator.itemgetter('segment_idx')):
            scene_idx = scene.get(
                'scene_idx',
                ch_idx * 1000 + scene['segment_idx'],
            )
            vid_asset_id = scene_asset_map.get(int(scene_idx))
            if not vid_asset_id:
                continue
            vid_bytes = await _fetch_asset_bytes(vid_asset_id)
            vid_file = tmp / f'vid_{int(scene_idx):04d}.mp4'
            await asyncio.to_thread(vid_file.write_bytes, vid_bytes)
            mezz_file = tmp / f'mezz_{int(scene_idx):04d}.mp4'
            await ffmpeg.mux_scene(
                video_path=str(vid_file),
                audio_path=audio_path,
                start_s=scene['start_s'],
                end_s=scene['end_s'],
                out_path=str(mezz_file),
            )
            scene_mezz_files.append(str(mezz_file))
        chapter_file = tmp / f'ch_{ch_idx:03d}_concat.mp4'
        await ffmpeg.concat_chapter(scene_mezz_files, str(chapter_file))
        chapter_files.append(str(chapter_file))
    return chapter_files


async def _build_music_paths(
    tmp: Path,
    scene_groups: dict[int, list[dict[str, Any]]],
    music_map: dict[int, dict[str, Any]],
) -> tuple[list[str], list[float]]:
    """Download music library assets; return paths and per-track gain_db."""
    music_paths: list[str] = []
    music_gains: list[float] = []
    for ch_idx in sorted(scene_groups.keys()):
        entry = music_map.get(ch_idx)
        if not entry:
            continue
        music_bytes = await _fetch_library_bytes(entry['library_asset_id'])
        music_file = tmp / f'music_{ch_idx:03d}.mp3'
        await asyncio.to_thread(music_file.write_bytes, music_bytes)
        music_paths.append(str(music_file))
        music_gains.append(float(entry.get('gain_db', 0.0)))
    return music_paths, music_gains


@register_stage
class AssemblyStage(Stage):
    """Stage 13: assemble motion, TTS, music, subtitles → FINAL_VIDEO asset."""

    key: ClassVar[str] = 'assembly'
    queue: ClassVar[str] = 'render'
    max_retries: ClassVar[int] = 1
    timeout_s: ClassVar[int] = 3600

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Assemble final video from all upstream stage outputs."""
        from server.apps.assets.models import AssetKind  # noqa: PLC0415
        from server.apps.rendering import ffmpeg  # noqa: PLC0415

        scene_asset_map = await _build_scene_asset_map(ctx)
        chapter_audio_map = await _build_chapter_audio_map(ctx)

        alignment = ctx.upstream.get('alignment', {})
        scenes = alignment.get('scenes', [])
        ass_asset_id: str | None = alignment.get('ass_asset_id')
        music_entries = ctx.upstream.get('music_plan', {}).get('entries', [])
        music_map = _build_music_map(music_entries)
        scene_groups = _group_scenes_by_chapter(scenes)
        watermark_asset_id, watermark_opacity = _resolve_watermark_config(ctx)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            ass_path: str | None = None
            if ass_asset_id:
                ass_bytes = await _fetch_asset_bytes(ass_asset_id)
                ass_file = tmp / 'captions.ass'
                await asyncio.to_thread(ass_file.write_bytes, ass_bytes)
                ass_path = str(ass_file)

            watermark_path: str | None = None
            if watermark_asset_id:
                wm_bytes = await _fetch_library_bytes(watermark_asset_id)
                wm_file = tmp / 'watermark.png'
                await asyncio.to_thread(wm_file.write_bytes, wm_bytes)
                watermark_path = str(wm_file)

            chapter_audio_files = await _write_chapter_audio_files(
                tmp,
                chapter_audio_map,
            )
            chapter_files = await _build_chapter_files(
                tmp,
                scene_groups,
                scene_asset_map,
                chapter_audio_files,
            )
            music_paths, music_gains = await _build_music_paths(
                tmp,
                scene_groups,
                music_map,
            )

            final_file = tmp / 'final.mp4'
            await ffmpeg.final_pass(
                chapter_paths=chapter_files,
                music_paths=music_paths,
                music_gains_db=music_gains,
                ass_path=ass_path,
                watermark_path=watermark_path,
                out_path=str(final_file),
                watermark_opacity=watermark_opacity,
            )

            probe = await ffmpeg.async_ffprobe(str(final_file))
            duration_s = float(probe.get('format', {}).get('duration', 0.0))
            video_bytes = await asyncio.to_thread(Path(final_file).read_bytes)

        asset = await ctx.assets.save(
            kind=AssetKind.FINAL_VIDEO,
            content=video_bytes,
            filename='final.mp4',
            mime='video/mp4',
        )
        return {'asset_id': str(asset.id), 'duration_s': duration_s}
