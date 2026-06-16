"""ClipAnalyzeStage — LLM analysis of transcript → ClipCandidate records."""

import asyncio
import json
from typing import Any, override

from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@register_stage
class ClipAnalyzeStage(Stage):
    """Stage 3: read analysis manifest → LLM → ClipCandidate records."""

    key = 'clip_analyze'
    queue = 'api'
    max_retries = 2
    timeout_s = 600

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Run LLM clip analysis and persist ClipCandidate records."""
        from server.apps.assets.models import Asset  # noqa: PLC0415
        from server.apps.clips.analysis import (  # noqa: PLC0415
            ClipAnalysisService,
        )

        manifest_asset_id: str = (
            ctx.upstream['clip_transcribe']['manifest_asset_id']
        )
        clips_requested: int = ctx.config.get('clips_requested', 5)

        manifest_asset = await Asset.objects.aget(id=manifest_asset_id)
        manifest_bytes = await asyncio.to_thread(manifest_asset.file.read)
        manifest: dict[str, Any] = json.loads(manifest_bytes)

        svc = ClipAnalysisService(run=ctx.run, clips_requested=clips_requested)
        candidates = await asyncio.to_thread(
            svc.analyze,
            transcript_text=manifest.get('transcript_text', ''),
            enriched_transcript=manifest.get('enriched_transcript', []),
            diarization={'segments': manifest.get('enriched_transcript', [])},
            scene_cuts=manifest.get('scene_cuts', []),
            video_duration=manifest.get('source_duration_sec'),
        )

        await ctx.costs.record(
            provider='anthropic',
            operation='clip_analysis',
            units=1,
            unit_cost_usd=0.05,
        )
        return {
            'candidate_ids': [str(c.id) for c in candidates],
            'candidate_count': len(candidates),
        }
