"""ClipManualSetup stage — create one manual ClipCandidate."""

import asyncio
import tempfile
from pathlib import Path
from typing import Any, override

from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@register_stage
class ClipManualSetupStage(Stage):
    """Stage 3 (manual flow): create a single is_manual ClipCandidate.

    Reads the ingested video duration — probing via ffprobe when the ingest
    stage could not determine it (e.g. library-asset uploads return 0.0) —
    then creates one ClipCandidate spanning the full video so the user can
    trim it during the gate review step.
    """

    key = 'clip_manual_setup'
    queue = 'render'
    max_retries = 1
    timeout_s = 300

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Create one manual ClipCandidate and return its ID."""
        from server.apps.assets.models import Asset  # noqa: PLC0415
        from server.apps.clips.logic.constants import (  # noqa: PLC0415
            CandidateStatus,
        )
        from server.apps.clips.models import ClipCandidate  # noqa: PLC0415
        from server.apps.rendering.ffmpeg import async_ffprobe  # noqa: PLC0415

        source_asset_id: str = ctx.upstream['clip_ingest']['asset_id']
        source_title: str = ctx.upstream['clip_ingest'].get('source_title', '')
        duration_sec: float = float(
            ctx.upstream['clip_ingest'].get('source_duration_sec', 0.0),
        )

        if not duration_sec:
            source_asset = await Asset.objects.aget(id=source_asset_id)
            video_bytes = await asyncio.to_thread(source_asset.file.read)
            with tempfile.TemporaryDirectory() as tmpdir:
                video_path = Path(tmpdir) / 'source.mp4'
                await asyncio.to_thread(video_path.write_bytes, video_bytes)
                probe = await async_ffprobe(str(video_path))
            duration_sec = float(
                probe.get('format', {}).get('duration', 0.0),
            )

        candidate = await ClipCandidate.objects.acreate(
            run=ctx.run,
            start_sec=0.0,
            end_sec=duration_sec,
            title=source_title or 'Full Video',
            is_manual=True,
            status=CandidateStatus.PROPOSED,
        )
        return {
            'candidate_ids': [str(candidate.id)],
            'candidate_count': 1,
        }
