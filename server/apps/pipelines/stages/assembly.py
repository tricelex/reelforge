"""Assembly stage — combine motion + TTS + music + subtitles → final video."""

import asyncio
import tempfile
from pathlib import Path
from typing import Any, ClassVar, override

from server.apps.pipelines.stages.base import Stage, StageContext, register_stage


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
    return await asyncio.to_thread(asset.file.read)  # type: ignore[no-any-return]


async def _fetch_library_bytes(library_asset_id: str) -> bytes:
    """Download bytes from a LibraryAsset by ID."""
    from server.apps.assets.models import LibraryAsset  # noqa: PLC0415

    asset = await LibraryAsset.objects.aget(id=library_asset_id)
    return await asyncio.to_thread(asset.file.read)  # type: ignore[no-any-return]


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
        raise NotImplementedError
