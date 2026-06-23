"""Read-only selectors for clipping run surfaces."""

import json
import uuid

from server.apps.pipelines.logic.value_objects import (
    TranscriptChapterPayload,
    TranscriptPayload,
    TranscriptWordPayload,
)
from server.apps.pipelines.models import StageExecution, StageStatus
from server.common.storage import PresignUrlHelper


def _latest_parent_execution(
    run_id: str,
    stage_key: str,
) -> StageExecution | None:
    return (
        StageExecution.objects  # type: ignore[misc]
        .filter(run_id=run_id, stage_key=stage_key, parent=None)
        .order_by('-attempt')
        .first()
    )


def _load_manifest_words(
    manifest_asset_id: str,
) -> tuple[list[TranscriptWordPayload], list[TranscriptChapterPayload]]:
    from server.apps.assets.models import Asset  # noqa: PLC0415

    asset = Asset.objects.get(id=uuid.UUID(manifest_asset_id))
    with asset.file.open('rb') as fh:
        raw = json.loads(fh.read())
    words = [
        TranscriptWordPayload(
            word=str(item.get('word', '')),
            start=float(item.get('start', 0)),
            end=float(item.get('end', 0)),
            speaker_id=str(item.get('speaker_id', '')),
        )
        for item in raw.get('enriched_transcript', [])
        if isinstance(item, dict)
    ]
    chapters = [
        TranscriptChapterPayload(start_sec=float(value))
        for value in raw.get('scene_cuts', [])
        if isinstance(value, (int, float))
    ]
    return words, chapters


def get_run_transcript(
    run_id: str,
    presign: PresignUrlHelper,
) -> TranscriptPayload:
    """Return transcript words and chapters from clip_transcribe output."""
    exec_ = _latest_parent_execution(run_id, 'clip_transcribe')
    if exec_ is None or exec_.status != StageStatus.SUCCEEDED:
        return TranscriptPayload(
            asset_id=None,
            source_asset_url=None,
            words=[],
            chapters=[],
        )

    transcript_id = exec_.output.get('transcript_asset_id')
    manifest_id = exec_.output.get('manifest_asset_id')
    if not transcript_id or not manifest_id:
        return TranscriptPayload(
            asset_id=None,
            source_asset_url=None,
            words=[],
            chapters=[],
        )

    from server.apps.assets.models import Asset  # noqa: PLC0415

    transcript = Asset.objects.get(id=uuid.UUID(str(transcript_id)))
    words, chapters = _load_manifest_words(str(manifest_id))
    return TranscriptPayload(
        asset_id=str(transcript_id),
        source_asset_url=presign.presign_get(transcript.file.name or ''),
        words=words,
        chapters=chapters,
    )
