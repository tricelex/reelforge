"""Load TTS fan-out shard data from child StageExecution rows."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.apps.pipelines.models import PipelineRun


async def load_tts_chapter_shards(run: 'PipelineRun') -> list[dict[str, Any]]:
    """Return latest SUCCEEDED tts child per shard, sorted by chapter_idx.

    Reads child executions directly so callers are not blocked by stale parent
    shard aggregates that only contain ``shard_index`` and ``status``.
    """
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    shards: list[dict[str, Any]] = []
    seen_shard_indices: set[int] = set()
    async for child in StageExecution.objects.filter(
        run=run,
        stage_key='tts',
        parent__isnull=False,
        status=StageStatus.SUCCEEDED,
    ).order_by('shard_index', '-attempt'):
        if child.shard_index is None or child.shard_index in seen_shard_indices:
            continue
        seen_shard_indices.add(child.shard_index)
        output = child.output or {}
        asset_id = output.get('asset_id')
        if not asset_id:
            continue
        chapter_idx = output.get('chapter_idx', child.shard_index)
        if chapter_idx is None:
            continue
        shards.append({
            'chapter_idx': int(chapter_idx),
            'asset_id': str(asset_id),
        })

    shards.sort(key=lambda shard: shard['chapter_idx'])
    return shards
