"""Full-quality clip export rendering, triggered from the editor."""

import hashlib
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from server.apps.clips.preview_render import _load_transcript_json
from server.apps.clips.selectors import (
    get_run_manifest_asset_id,
    get_run_source_asset_id,
)

if TYPE_CHECKING:
    from server.apps.assets.models import Asset
    from server.apps.clips.models import ClipCandidate

logger = structlog.get_logger(__name__)

EXPORT_CACHE_PREFIX = 'clip_export:'
EXPORT_CACHE_TIMEOUT = 3600
EXPORT_CRF = 18
EXPORT_PRESET = 'slow'


def export_cache_key(candidate_id: str) -> str:
    """Return the Django cache key for one candidate export job."""
    return f'{EXPORT_CACHE_PREFIX}{candidate_id}'


def get_export_state(candidate_id: str) -> dict[str, Any] | None:
    """Return the cached export job state, or None when absent."""
    from django.core.cache import cache  # noqa: PLC0415

    cached = cache.get(export_cache_key(candidate_id))
    if isinstance(cached, dict):
        return cached
    return None


def set_export_queued(candidate_id: str) -> None:
    """Mark the export job as queued."""
    _set_export_state(candidate_id, {'status': 'queued'})


def _set_export_state(candidate_id: str, state: dict[str, Any]) -> None:
    from django.core.cache import cache  # noqa: PLC0415

    cache.set(
        export_cache_key(candidate_id),
        state,
        timeout=EXPORT_CACHE_TIMEOUT,
    )


def _set_export_failed(candidate_id: str, error: str) -> None:
    _set_export_state(
        candidate_id,
        {'status': 'failed', 'error': error[:500]},
    )


def _save_export_asset(
    *,
    run_id: uuid.UUID,
    candidate_id: str,
    content: bytes,
) -> uuid.UUID:
    from django.core.files.base import ContentFile  # noqa: PLC0415

    from server.apps.assets.models import Asset, AssetKind  # noqa: PLC0415

    checksum = hashlib.sha256(content).hexdigest()
    asset = Asset(
        kind=AssetKind.FINAL_VIDEO,
        mime='video/mp4',
        checksum=checksum,
        run_id=run_id,
    )
    asset.file.save(
        f'clip_{candidate_id}.mp4',
        ContentFile(content),
        save=False,
    )
    asset.save()
    return asset.id


def _run_export_pipeline(
    *,
    candidate: 'ClipCandidate',
    candidate_id: str,
    source_asset: 'Asset',
    transcript_json: dict[str, Any],
    timed_overlays: list[Any],
    timed_sfx: list[Any],
) -> bytes:
    from server.apps.clips.logic.constants import (  # noqa: PLC0415
        render_format_dimensions,
    )
    from server.apps.rendering.clip_render_pipeline import (  # noqa: PLC0415
        ClipRenderPipeline,
        PipelineRenderConfig,
    )

    width, height = render_format_dimensions(
        candidate.layout_config.render_format,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        src_path = tmp / 'source.mp4'
        out_path = tmp / 'export.mp4'
        from server.common.asset_cache import (  # noqa: PLC0415
            materialize_to_path,
        )

        materialize_to_path(
            checksum=source_asset.checksum,
            open_stream=lambda: source_asset.file.open('rb'),
            destination=src_path,
        )

        config = PipelineRenderConfig(
            source_path=src_path,
            output_path=out_path,
            start_sec=candidate.start_sec,
            end_sec=candidate.end_sec,
            hook_text=candidate.hook_text,
            transcript_json=transcript_json,
            layout_config=candidate.layout_config,
            style_config=candidate.style_config,
            timed_overlays=timed_overlays,
            timed_sfx=timed_sfx,
            render_id=f'export-{candidate_id}-{uuid.uuid4()}',
            width=width,
            height=height,
            crf=EXPORT_CRF,
            preset=EXPORT_PRESET,
        )
        render_dir = (
            Path(tempfile.gettempdir()) / 'clip_renders' / config.render_id
        )
        try:
            ClipRenderPipeline(config).run()
        finally:
            shutil.rmtree(render_dir, ignore_errors=True)
        return out_path.read_bytes()


def _persist_export(
    candidate: 'ClipCandidate',
    candidate_id: str,
    rendered_bytes: bytes,
) -> None:
    from server.apps.clips.logic.constants import (  # noqa: PLC0415
        CandidateStatus,
    )

    render_asset_id = _save_export_asset(
        run_id=candidate.run_id,
        candidate_id=candidate_id,
        content=rendered_bytes,
    )
    candidate.render_asset_id = render_asset_id
    candidate.status = CandidateStatus.RENDERED
    candidate.save(update_fields=['render_asset_id', 'status', 'updated_at'])
    _set_export_state(candidate_id, {'status': 'ready'})
    logger.info(
        'clip_export_rendered',
        candidate_id=candidate_id,
        render_asset_id=str(render_asset_id),
    )


def render_clip_export_sync(candidate_id: str) -> None:
    """Render a full-quality MP4 and persist it on the candidate."""
    from server.apps.assets.models import Asset  # noqa: PLC0415
    from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

    candidate = ClipCandidate.objects.select_related(
        'layout_config',
        'style_config',
        'run',
    ).get(id=candidate_id)

    run_id = str(candidate.run_id)
    source_asset_id = get_run_source_asset_id(run_id)
    manifest_asset_id = get_run_manifest_asset_id(run_id)
    if source_asset_id is None:
        _set_export_failed(candidate_id, 'Source video is not ready yet.')
        return
    if manifest_asset_id is None:
        _set_export_failed(candidate_id, 'Transcript is not ready yet.')
        return

    timed_overlays = list(candidate.timed_overlays.all())
    timed_sfx = list(candidate.timed_sfx.all())
    source_asset = Asset.objects.get(id=uuid.UUID(source_asset_id))
    transcript_json = _load_transcript_json(manifest_asset_id)

    _set_export_state(candidate_id, {'status': 'rendering'})

    try:
        rendered_bytes = _run_export_pipeline(
            candidate=candidate,
            candidate_id=candidate_id,
            source_asset=source_asset,
            transcript_json=transcript_json,
            timed_overlays=timed_overlays,
            timed_sfx=timed_sfx,
        )
    except Exception as exc:
        logger.exception(
            'clip_export_render_failed',
            candidate_id=candidate_id,
        )
        _set_export_failed(candidate_id, str(exc))
        return

    _persist_export(candidate, candidate_id, rendered_bytes)
