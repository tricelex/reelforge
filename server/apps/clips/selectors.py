"""Read-only selectors for clip editor surfaces."""

import asyncio
import tempfile
import uuid
from pathlib import Path
from typing import Any

from server.apps.pipelines.models import StageExecution, StageStatus


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


def get_run_source_asset_id(run_id: str) -> str | None:
    """Return clip_ingest source asset ID for a run, if available."""
    exec_ = _latest_parent_execution(run_id, 'clip_ingest')
    if exec_ is None or exec_.status != StageStatus.SUCCEEDED:
        return None
    asset_id = exec_.output.get('asset_id')
    if not asset_id:
        return None
    return str(asset_id)


def get_run_manifest_asset_id(run_id: str) -> str | None:
    """Return clip_transcribe manifest asset ID for a run, if available."""
    exec_ = _latest_parent_execution(run_id, 'clip_transcribe')
    if exec_ is None or exec_.status != StageStatus.SUCCEEDED:
        return None
    manifest_id = exec_.output.get('manifest_asset_id')
    if not manifest_id:
        return None
    return str(manifest_id)


def dimensions_from_probe(probe: dict[str, Any]) -> tuple[int | None, int | None]:
    for stream in probe.get('streams', []):
        if stream.get('codec_type') != 'video':
            continue
        width = stream.get('width')
        height = stream.get('height')
        if isinstance(width, int) and isinstance(height, int):
            return width, height
    return None, None


def probe_local_video_dimensions(path: str) -> tuple[int | None, int | None]:
    """Run ffprobe on a local file and return video width/height."""
    from server.apps.rendering.ffmpeg import async_ffprobe  # noqa: PLC0415

    try:
        probe = asyncio.run(async_ffprobe(path))
    except RuntimeError:
        return None, None
    return dimensions_from_probe(probe)


def get_asset_dimensions(asset_id: str) -> tuple[int | None, int | None]:
    """Return source video dimensions, probing and caching in asset meta."""
    from server.apps.assets.models import Asset  # noqa: PLC0415

    asset = Asset.objects.get(id=uuid.UUID(asset_id))
    meta = dict(asset.meta)
    width = meta.get('width')
    height = meta.get('height')
    if isinstance(width, int) and isinstance(height, int):
        return width, height

    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        from server.common.asset_cache import (  # noqa: PLC0415
            materialize_to_path,
        )

        materialize_to_path(
            checksum=asset.checksum,
            open_stream=lambda: asset.file.open('rb'),
            destination=Path(tmp_path),
        )
        probed_w, probed_h = probe_local_video_dimensions(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if probed_w is not None and probed_h is not None:
        meta['width'] = probed_w
        meta['height'] = probed_h
        asset.meta = meta
        asset.save(update_fields=['meta'])
    return probed_w, probed_h


def get_candidate_source_dimensions(
    candidate_id: str,
) -> tuple[int | None, int | None]:
    """Resolve source video dimensions for a clip candidate."""
    from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

    candidate = ClipCandidate.objects.select_related('run').get(
        id=candidate_id,
    )
    asset_id = get_run_source_asset_id(str(candidate.run_id))
    if asset_id is None:
        return None, None
    return get_asset_dimensions(asset_id)
