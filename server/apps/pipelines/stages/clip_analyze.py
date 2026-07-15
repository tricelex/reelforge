"""ClipAnalyzeStage — diarization + LLM analysis → ClipCandidate records."""

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any, override

import structlog

from server.apps.clips.logic.transcript_merge import (
    diarization_payload,
    merge_transcript_with_diarization,
)
from server.apps.generation.logic.constants import DEFAULT_LLM_PROVIDER
from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)

logger = structlog.get_logger(__name__)


def _run_diarization(video_path: Path) -> list[dict[str, Any]]:
    """Run speaker diarization; caller handles exceptions."""
    from server.apps.rendering.speaker_detection import (  # noqa: PLC0415
        SpeakerDetectionService,
    )

    return SpeakerDetectionService().diarize(video_path)


def _update_manifest_asset(
    manifest_asset: Any,
    manifest: dict[str, Any],
) -> None:
    """Overwrite manifest asset content with updated analysis data."""
    import hashlib as hashlib_module  # noqa: PLC0415

    from django.core.files.base import ContentFile  # noqa: PLC0415

    content = json.dumps(manifest).encode()
    manifest_asset.checksum = hashlib_module.sha256(content).hexdigest()
    manifest_asset.file.save(
        'analysis_manifest.json',
        ContentFile(content),
        save=False,
    )
    manifest_asset.save(update_fields=['file', 'checksum', 'updated_at'])


@register_stage
class ClipAnalyzeStage(Stage):
    """Stage 3: diarize, merge transcript, LLM → ClipCandidate records."""

    key = 'clip_analyze'
    queue = 'render'
    max_retries = 2
    timeout_s = 3600

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        """Run diarization + LLM clip analysis and persist candidates."""
        from server.apps.assets.models import Asset  # noqa: PLC0415
        from server.apps.clips.analysis import (  # noqa: PLC0415
            ClipAnalysisService,
        )

        manifest_asset_id: str = ctx.upstream['clip_transcribe'][
            'manifest_asset_id'
        ]
        source_asset_id: str = ctx.upstream['clip_ingest']['asset_id']
        clips_requested: int = ctx.config.get('clips_requested', 5)

        manifest_asset = await Asset.objects.aget(id=manifest_asset_id)
        source_asset = await Asset.objects.aget(id=source_asset_id)
        manifest_bytes = await asyncio.to_thread(manifest_asset.file.read)
        manifest: dict[str, Any] = json.loads(manifest_bytes)
        video_bytes = await asyncio.to_thread(source_asset.file.read)

        diar_segments: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / 'source.mp4'
            await asyncio.to_thread(video_path.write_bytes, video_bytes)
            try:
                logger.info('clip_analyze_diarize', run_id=str(ctx.run.id))
                diar_segments = await asyncio.to_thread(
                    _run_diarization,
                    video_path,
                )
            except Exception as exc:
                logger.warning(
                    'clip_analyze_diarize_failed',
                    run_id=str(ctx.run.id),
                    error=str(exc),
                )
                from server.common.exceptions import (  # noqa: PLC0415
                    FatalProviderError,
                )

                if isinstance(exc, FatalProviderError):
                    raise
                raise FatalProviderError(
                    f'Speaker diarization failed: {exc}',
                    provider='pyannoteai',
                    error_code='diarization_failed',
                ) from exc

        enriched = merge_transcript_with_diarization(
            manifest.get('enriched_transcript', []),
            diar_segments,
        )
        diarization = diarization_payload(diar_segments)
        manifest['enriched_transcript'] = enriched
        manifest['diarization'] = diarization
        await asyncio.to_thread(
            _update_manifest_asset,
            manifest_asset,
            manifest,
        )

        svc = ClipAnalysisService(run=ctx.run, clips_requested=clips_requested)
        candidates = await asyncio.to_thread(
            svc.analyze,
            transcript_text=manifest.get('transcript_text', ''),
            enriched_transcript=enriched,
            diarization=diarization,
            scene_cuts=manifest.get('scene_cuts', []),
            video_duration=manifest.get('source_duration_sec'),
        )

        await ctx.costs.record(
            provider=DEFAULT_LLM_PROVIDER,
            operation='clip_analysis',
            units=1,
            unit_cost_usd=0.05,
        )
        return {
            'candidate_ids': [str(c.id) for c in candidates],
            'candidate_count': len(candidates),
        }
