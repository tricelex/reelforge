"""Assembly stage — combine motion + TTS + music + subtitles → final video."""

import asyncio
import operator
import tempfile
from pathlib import Path
from typing import Any, ClassVar, override

import structlog

from server.apps.pipelines.logic.pool_rotation import pick_cyclic
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)

logger = structlog.get_logger(__name__)

_DEFAULT_TRANSITION = 'hard_cut'
_TRANSITION_DURATION_S = 0.5
_MUSIC_GAIN_DEFAULT_DB = -22.0
_MUSIC_GAIN_MIN_DB = -24.0
_MUSIC_GAIN_MAX_DB = -6.0
# worker-render is capped at 4 vCPUs in production (docker-compose.vps.yml)
# and each mux_scene call is its own multi-threaded ffmpeg encode — keep
# concurrent scenes low enough that they don't starve each other, not so
# low that scene-heavy chapters stay fully sequential.
_SCENE_MUX_CONCURRENCY = 3


def _clamp_music_gain_db(gain_db: float) -> float:
    """Clamp bed music gain into the safe documentary range."""
    return max(_MUSIC_GAIN_MIN_DB, min(_MUSIC_GAIN_MAX_DB, gain_db))


def _resolve_channel_music_bed_gain_db(channel: object) -> float:
    """Return channel bed gain, or the quiet documentary default (-22)."""
    from server.apps.channels.models import (  # noqa: PLC0415
        AssemblyStyleConfig,
    )

    try:
        style = channel.assembly_style  # type: ignore[attr-defined]
    except AssemblyStyleConfig.DoesNotExist:
        return _MUSIC_GAIN_DEFAULT_DB
    except AttributeError:
        return _MUSIC_GAIN_DEFAULT_DB
    return _clamp_music_gain_db(float(style.music_bed_gain_db))


def _effective_music_gain_db(
    entry: dict[str, Any],
    *,
    channel_bed_gain_db: float,
) -> float:
    """Apply channel bed gain (default -22); ignore legacy loud plan values.

    ``music_plan.gain_db`` historically defaulted to ``0.0`` and often stays
    too hot. Channel style (or the -22 fallback) is the operator control.
    """
    del entry  # plan picks the track; channel style owns bed level
    return _clamp_music_gain_db(channel_bed_gain_db)


def _pick_transition_style(pool: list[str], chapter_idx: int) -> str:
    """Cycle through the channel's transition-style pool by chapter index."""
    return pick_cyclic(pool, chapter_idx, _DEFAULT_TRANSITION)


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
    """Index music_plan entries by chapter_idx (legacy multi-entry plans)."""
    return {e['chapter_idx']: e for e in entries}


def _candidate_music_asset_ids(music_plan: dict[str, Any]) -> list[str]:
    """Return unique library asset IDs from a single-bed or legacy plan.

    Prefer the modern ``library_asset_id`` field. Fall back to legacy
    per-chapter ``entries``, preserving first-seen order and deduplicating.
    """
    direct = music_plan.get('library_asset_id')
    if direct:
        return [str(direct)]
    candidates: list[str] = []
    seen: set[str] = set()
    for entry in music_plan.get('entries') or []:
        asset_id = entry.get('library_asset_id')
        if not asset_id:
            continue
        key = str(asset_id)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(key)
    return candidates


def _resolve_segment_stage(ctx: StageContext) -> str:
    """Return the stage key that produced this run's video segments."""
    from server.apps.pipelines.logic.blueprint_profiles import (  # noqa: PLC0415
        SEGMENT_STAGE,
        resolve_role,
    )

    return resolve_role(ctx.run.blueprint_snapshot or {}, SEGMENT_STAGE)


async def _build_scene_asset_map(ctx: StageContext) -> dict[int, str]:
    """Return {scene_idx: asset_id} from the run's segment stage children."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    scene_map: dict[int, str] = {}
    async for child in StageExecution.objects.filter(
        run=ctx.run,
        stage_key=_resolve_segment_stage(ctx),
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
    from server.apps.pipelines.services.tts_shards import (  # noqa: PLC0415
        load_tts_chapter_shards,
    )

    return {
        shard['chapter_idx']: shard['asset_id']
        for shard in await load_tts_chapter_shards(ctx.run)
    }


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


def _normalize_chapter_origins(
    raw: dict[Any, Any] | None,
) -> dict[int, float] | None:
    """Coerce alignment ``chapter_origins`` keys to int (JSON may stringify)."""
    if not raw:
        return None
    return {int(k): float(v) for k, v in raw.items()}


async def _probe_chapter_audio_origins(
    chapter_audio_files: dict[int, str],
    chapter_idxs: list[int],
) -> dict[int, float]:
    """Infer absolute t=0 per chapter from cumulative TTS file durations."""
    from server.apps.rendering.ffmpeg import async_ffprobe  # noqa: PLC0415

    origins: dict[int, float] = {}
    cumulative = 0.0
    for ch_idx in chapter_idxs:
        origins[ch_idx] = cumulative
        path = chapter_audio_files.get(ch_idx)
        if not path:
            continue
        probe = await async_ffprobe(path)
        duration = float(probe.get('format', {}).get('duration', 0.0) or 0.0)
        cumulative += max(0.0, duration)
    return origins


async def _resolve_chapter_origins(
    chapter_audio_files: dict[int, str],
    chapter_idxs: list[int],
    alignment_origins: dict[Any, Any] | None,
) -> dict[int, float]:
    """Prefer alignment-stored origins; fall back to probing TTS durations."""
    normalized = _normalize_chapter_origins(alignment_origins)
    if normalized is not None:
        return normalized
    return await _probe_chapter_audio_origins(
        chapter_audio_files,
        chapter_idxs,
    )


def _chapter_relative_window(
    start_s: float,
    end_s: float,
    chapter_origin_s: float,
) -> tuple[float, float]:
    """Convert absolute alignment times to chapter-TTS atrim window."""
    rel_start = start_s - chapter_origin_s
    rel_end = end_s - chapter_origin_s
    rel_start = max(rel_start, 0.0)
    if rel_end <= rel_start:
        raise ValueError(
            'chapter-relative atrim window is empty '
            f'(absolute {start_s}-{end_s}, origin {chapter_origin_s})',
        )
    return rel_start, rel_end


async def _mux_one_scene(
    tmp: Path,
    ch_idx: int,
    scene: dict[str, Any],
    scene_asset_map: dict[int, str],
    audio_path: str,
    origin: float,
    semaphore: asyncio.Semaphore,
) -> tuple[int, str | None]:
    """Fetch, fit, and mux a single scene; return (scene_idx, mezz_path).

    ``mezz_path`` is ``None`` when the scene has no mapped motion asset —
    the caller collects those into a combined ``missing`` error rather than
    failing on the first one, matching the previous sequential behavior.

    Raises:
        ValueError: If the scene lacks ``scene_idx``.
    """
    from server.apps.rendering import ffmpeg  # noqa: PLC0415

    if 'scene_idx' not in scene:
        raise ValueError(
            f'assembly chapter {ch_idx}: alignment scene missing '
            'scene_idx (re-run alignment after scene_breakdown)',
        )
    scene_idx = int(scene['scene_idx'])
    vid_asset_id = scene_asset_map.get(scene_idx)
    if not vid_asset_id:
        return scene_idx, None

    async with semaphore:
        vid_bytes = await _fetch_asset_bytes(vid_asset_id)
        vid_file = tmp / f'vid_{scene_idx:04d}.mp4'
        await asyncio.to_thread(vid_file.write_bytes, vid_bytes)
        mezz_file = tmp / f'mezz_{scene_idx:04d}.mp4'
        rel_start, rel_end = _chapter_relative_window(
            float(scene['start_s']),
            float(scene['end_s']),
            origin,
        )
        await ffmpeg.mux_scene(
            video_path=str(vid_file),
            audio_path=audio_path,
            start_s=rel_start,
            end_s=rel_end,
            out_path=str(mezz_file),
        )
    return scene_idx, str(mezz_file)


def _collect_scene_mux_results(
    results: list[Any],
    ch_idx: int,
) -> list[str]:
    """Split gathered (scene_idx, mezz_path) results; raise on failures.

    Raises:
        BaseException: The first exception raised by any scene's mux task.
        ValueError: If any scene is missing its motion asset, or the
            chapter ends up with zero mezzanine segments to concat.
    """
    scene_mezz_files: list[str] = []
    missing: list[int] = []
    for result in results:
        if isinstance(result, BaseException):
            raise result
        scene_idx, mezz_path = result
        if mezz_path is None:
            missing.append(scene_idx)
        else:
            scene_mezz_files.append(mezz_path)
    if missing:
        raise ValueError(
            f'assembly chapter {ch_idx}: missing motion assets for '
            f'scene_idx={missing}',
        )
    if not scene_mezz_files:
        raise ValueError(
            f'assembly chapter {ch_idx}: no mezzanine segments to concat',
        )
    return scene_mezz_files


async def _build_chapter_files(
    tmp: Path,
    scene_groups: dict[int, list[dict[str, Any]]],
    scene_asset_map: dict[int, str],
    chapter_audio_files: dict[int, str],
    transition_pool: list[str],
    chapter_origins: dict[Any, Any] | None = None,
) -> list[str]:
    """Mux scenes per chapter and concat; return ordered chapter file paths.

    Alignment ``start_s`` / ``end_s`` are absolute on the narration timeline.
    Each chapter TTS file is timed from zero, so windows are shifted by the
    chapter origin before ``mux_scene``. Scenes within a chapter are muxed
    concurrently (bounded by ``_SCENE_MUX_CONCURRENCY``) since each is an
    independent ffmpeg subprocess with no shared state.

    Raises:
        ValueError: If a scene lacks ``scene_idx``, its motion asset is
            missing, or a chapter would concat zero mezzanine files.
    """
    from server.apps.rendering import ffmpeg  # noqa: PLC0415

    origins = await _resolve_chapter_origins(
        chapter_audio_files,
        list(scene_groups.keys()),
        chapter_origins,
    )

    chapter_files: list[str] = []
    for ch_idx, ch_scenes in scene_groups.items():
        audio_path = chapter_audio_files.get(ch_idx, '')
        if not audio_path:
            raise ValueError(
                f'assembly chapter {ch_idx}: missing TTS audio asset',
            )
        origin = origins.get(ch_idx, 0.0)
        ordered_scenes = sorted(
            ch_scenes,
            key=operator.itemgetter('segment_idx'),
        )
        semaphore = asyncio.Semaphore(_SCENE_MUX_CONCURRENCY)
        results = await asyncio.gather(
            *(
                _mux_one_scene(
                    tmp,
                    ch_idx,
                    scene,
                    scene_asset_map,
                    audio_path,
                    origin,
                    semaphore,
                )
                for scene in ordered_scenes
            ),
            return_exceptions=True,
        )

        scene_mezz_files = _collect_scene_mux_results(results, ch_idx)
        transition = _pick_transition_style(transition_pool, ch_idx)
        chapter_file = tmp / f'ch_{ch_idx:03d}_concat.mp4'
        await ffmpeg.concat_chapter_with_transition(
            scene_mezz_files,
            transition,
            _TRANSITION_DURATION_S,
            str(chapter_file),
        )
        chapter_files.append(str(chapter_file))
    return chapter_files


async def _build_music_paths(
    tmp: Path,
    music_plan: dict[str, Any],
    *,
    channel_bed_gain_db: float = _MUSIC_GAIN_DEFAULT_DB,
) -> tuple[list[str], list[float]]:
    """Download at most one music library asset; return path and bed gain.

    Skips (rather than crashes the render on) a plan whose
    library_asset_id doesn't resolve to a real LibraryAsset — e.g. the
    music_plan LLM hallucinated an ID. Legacy multi-entry plans try
    candidates in order until one resolves; only the first successful
    download is used so beds are never layered.

    Channel ``music_bed_gain_db`` (default -22) wins over loud/legacy plan
    gains so assembly-only reruns stay quiet without re-running music_plan.
    """
    from django.core.exceptions import ObjectDoesNotExist  # noqa: PLC0415

    for asset_id in _candidate_music_asset_ids(music_plan):
        try:
            music_bytes = await _fetch_library_bytes(asset_id)
        except ObjectDoesNotExist:
            logger.warning(
                'assembly_music_asset_missing',
                library_asset_id=asset_id,
            )
            continue
        music_file = tmp / 'music_bed.mp3'
        await asyncio.to_thread(music_file.write_bytes, music_bytes)
        gain = _effective_music_gain_db(
            {},
            channel_bed_gain_db=channel_bed_gain_db,
        )
        return [str(music_file)], [gain]
    return [], []


async def _resolve_ass_path(
    tmp: Path,
    *,
    scenes: list[dict[str, Any]],
    ass_asset_id: str | None,
) -> str | None:
    """Build chunked ASS from alignment words; fall back to stored ASS asset.

    Regenerating at assembly time means an assembly-only rerun picks up
    caption timing fixes without re-calling forced alignment.
    """
    from server.apps.pipelines.stages.alignment import (  # noqa: PLC0415
        _build_ass_content,
        _subtitle_segments_from_scenes,
    )

    segments = _subtitle_segments_from_scenes(scenes)
    if segments:
        ass_file = tmp / 'captions.ass'
        await asyncio.to_thread(
            ass_file.write_bytes,
            _build_ass_content(segments),
        )
        return str(ass_file)
    if not ass_asset_id:
        return None
    ass_bytes = await _fetch_asset_bytes(ass_asset_id)
    ass_file = tmp / 'captions.ass'
    await asyncio.to_thread(ass_file.write_bytes, ass_bytes)
    return str(ass_file)


_SFX_GAIN_DB = -12.0
_SFX_LIMIT = 3


async def _build_sfx_paths(
    tmp: Path,
    ctx: StageContext,
) -> tuple[list[str], list[float]]:
    """Download up to 3 SFX tracks matching the channel's sfx_pool_tags."""
    from server.apps.assets.models import (  # noqa: PLC0415
        LibraryAsset,
        LibraryAssetKind,
    )

    tags = getattr(ctx.channel, 'assembly_style_sfx_pool_tags', [])
    if not tags:
        return [], []
    assets_qs = LibraryAsset.objects.filter(
        kind=LibraryAssetKind.SFX,
        is_active=True,
        tags__overlap=tags,
    ).order_by('name')[:_SFX_LIMIT]

    sfx_paths: list[str] = []
    sfx_gains: list[float] = []
    async for asset in assets_qs:
        sfx_bytes = await _fetch_library_bytes(str(asset.id))
        sfx_file = tmp / f'sfx_{asset.id}.mp3'
        await asyncio.to_thread(sfx_file.write_bytes, sfx_bytes)
        sfx_paths.append(str(sfx_file))
        sfx_gains.append(_SFX_GAIN_DB)
    return sfx_paths, sfx_gains


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
        music_plan = ctx.upstream.get('music_plan', {})
        scene_groups = _group_scenes_by_chapter(scenes)
        watermark_asset_id, watermark_opacity = _resolve_watermark_config(ctx)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            ass_path = await _resolve_ass_path(
                tmp,
                scenes=scenes,
                ass_asset_id=ass_asset_id,
            )

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
            transition_pool = getattr(
                ctx.channel,
                'assembly_style_transition_styles',
                [],
            )
            chapter_files = await _build_chapter_files(
                tmp,
                scene_groups,
                scene_asset_map,
                chapter_audio_files,
                transition_pool,
                chapter_origins=alignment.get('chapter_origins'),
            )
            music_paths, music_gains = await _build_music_paths(
                tmp,
                music_plan,
                channel_bed_gain_db=_resolve_channel_music_bed_gain_db(
                    ctx.channel,
                ),
            )
            sfx_paths, sfx_gains = await _build_sfx_paths(tmp, ctx)

            final_file = tmp / 'final.mp4'
            await ffmpeg.final_pass(
                chapter_paths=chapter_files,
                music_paths=music_paths,
                music_gains_db=music_gains,
                ass_path=ass_path,
                watermark_path=watermark_path,
                out_path=str(final_file),
                watermark_opacity=watermark_opacity,
                sfx_paths=sfx_paths,
                sfx_gains_db=sfx_gains,
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
