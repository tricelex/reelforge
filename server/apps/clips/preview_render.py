"""Lightweight clip preview rendering for the editor."""

import hashlib
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from server.apps.clips.selectors import (
    get_run_manifest_asset_id,
    get_run_source_asset_id,
)

if TYPE_CHECKING:
    from server.apps.assets.models import Asset
    from server.apps.clips.models import (
        ClipCandidate,
        ClipTimedOverlay,
    )

logger = structlog.get_logger(__name__)

PREVIEW_CACHE_PREFIX = 'clip_preview:'
PREVIEW_WORKER_LOCK_SUFFIX = ':worker'
PREVIEW_CACHE_TIMEOUT = 3600
PREVIEW_WIDTH = 540
PREVIEW_HEIGHT = 960
PREVIEW_CRF = 28
PREVIEW_PRESET = 'veryfast'


def preview_cache_key(candidate_id: str) -> str:
    """Return the Django cache key for one candidate preview job."""
    return f'{PREVIEW_CACHE_PREFIX}{candidate_id}'


def preview_worker_lock_key(candidate_id: str) -> str:
    """Return the cache key used to claim one preview worker at a time."""
    return f'{preview_cache_key(candidate_id)}{PREVIEW_WORKER_LOCK_SUFFIX}'


def preview_config_version(candidate_id: str) -> int:
    """Return a monotonic-ish version from candidate + config timestamps."""
    from django.db.models import Max  # noqa: PLC0415

    from server.apps.clips.models import (  # noqa: PLC0415
        ClipCandidate,
        ClipLayoutConfig,
        ClipStyleConfig,
        ClipTimedOverlay,
    )

    candidate = ClipCandidate.objects.get(id=candidate_id)
    version = int(candidate.updated_at.timestamp())
    try:
        layout = ClipLayoutConfig.objects.get(candidate_id=candidate_id)
        version += int(layout.updated_at.timestamp())
    except ClipLayoutConfig.DoesNotExist:
        pass
    try:
        style = ClipStyleConfig.objects.get(candidate_id=candidate_id)
        version += int(style.updated_at.timestamp())
    except ClipStyleConfig.DoesNotExist:
        pass
    overlay_max = ClipTimedOverlay.objects.filter(
        candidate_id=candidate_id,
    ).aggregate(updated_at__max=Max('updated_at'))['updated_at__max']
    if overlay_max is not None:
        version += int(overlay_max.timestamp())
    return version


def invalidate_preview_cache(candidate_id: str) -> None:
    """Clear preview job state so the next trigger can enqueue."""
    from django.core.cache import cache  # noqa: PLC0415

    cache.delete(preview_cache_key(candidate_id))
    cache.delete(preview_worker_lock_key(candidate_id))


def _set_preview_failed(candidate_id: str, error: str) -> None:
    from django.core.cache import cache  # noqa: PLC0415

    cache.set(
        preview_cache_key(candidate_id),
        {'status': 'failed', 'error': error[:500]},
        timeout=PREVIEW_CACHE_TIMEOUT,
    )


def _set_preview_ready(candidate_id: str, config_version: int) -> None:
    from django.core.cache import cache  # noqa: PLC0415

    cache.set(
        preview_cache_key(candidate_id),
        {'status': 'ready', 'config_version': config_version},
        timeout=PREVIEW_CACHE_TIMEOUT,
    )
    cache.delete(preview_worker_lock_key(candidate_id))


def _try_claim_preview_worker(candidate_id: str) -> bool:
    from django.core.cache import cache  # noqa: PLC0415

    return cache.add(
        preview_worker_lock_key(candidate_id),
        '1',
        timeout=PREVIEW_CACHE_TIMEOUT,
    )


def _preview_already_ready(
    candidate_id: str,
    candidate: 'ClipCandidate',
) -> bool:
    from django.core.cache import cache  # noqa: PLC0415

    if candidate.preview_asset_id is None:
        return False
    version = preview_config_version(candidate_id)
    cached = cache.get(preview_cache_key(candidate_id))
    if not isinstance(cached, dict):
        return False
    return (
        cached.get('status') == 'ready'
        and cached.get('config_version') == version
    )


def _save_preview_asset(
    *,
    run_id: uuid.UUID,
    candidate_id: str,
    content: bytes,
) -> uuid.UUID:
    from django.core.files.base import ContentFile  # noqa: PLC0415

    from server.apps.assets.models import Asset, AssetKind  # noqa: PLC0415

    checksum = hashlib.sha256(content).hexdigest()
    asset = Asset(
        kind=AssetKind.VIDEO_SEGMENT,
        mime='video/mp4',
        checksum=checksum,
        run_id=run_id,
    )
    asset.file.save(
        f'preview_{candidate_id}.mp4',
        ContentFile(content),
        save=False,
    )
    asset.save()
    return asset.id


def _load_transcript_json(manifest_asset_id: str) -> dict[str, Any]:
    from server.apps.assets.models import Asset  # noqa: PLC0415

    asset = Asset.objects.get(id=uuid.UUID(manifest_asset_id))
    with asset.file.open('rb') as fh:
        manifest: dict[str, Any] = json.loads(fh.read())
    transcript_json = manifest.get('transcript_json', {})
    if isinstance(transcript_json, dict):
        return transcript_json
    return {}


def _run_preview_pipeline(
    *,
    candidate: 'ClipCandidate',
    candidate_id: str,
    source_asset: 'Asset',
    transcript_json: dict[str, Any],
    timed_overlays: list['ClipTimedOverlay'],
) -> bytes:
    from server.apps.rendering.clip_render_pipeline import (  # noqa: PLC0415
        ClipRenderPipeline,
        PipelineRenderConfig,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        src_path = tmp / 'source.mp4'
        out_path = tmp / 'preview.mp4'
        with source_asset.file.open('rb') as fh:
            src_path.write_bytes(fh.read())

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
            render_id=f'preview-{candidate_id}-{uuid.uuid4()}',
            width=PREVIEW_WIDTH,
            height=PREVIEW_HEIGHT,
            crf=PREVIEW_CRF,
            preset=PREVIEW_PRESET,
        )
        render_dir = (
            Path(tempfile.gettempdir()) / 'clip_renders' / config.render_id
        )
        try:
            ClipRenderPipeline(config).run()
        finally:
            shutil.rmtree(render_dir, ignore_errors=True)
        return out_path.read_bytes()


def _persist_preview(
    candidate: 'ClipCandidate',
    candidate_id: str,
    rendered_bytes: bytes,
) -> None:
    preview_asset_id = _save_preview_asset(
        run_id=candidate.run_id,
        candidate_id=candidate_id,
        content=rendered_bytes,
    )
    candidate.preview_asset_id = preview_asset_id
    candidate.save(update_fields=['preview_asset_id', 'updated_at'])
    _set_preview_ready(
        candidate_id,
        preview_config_version(candidate_id),
    )
    logger.info(
        'clip_preview_rendered',
        candidate_id=candidate_id,
        preview_asset_id=str(preview_asset_id),
    )


def render_clip_preview_sync(candidate_id: str) -> None:
    """Render a low-quality preview MP4 and persist it on the candidate."""
    from django.core.cache import cache  # noqa: PLC0415

    from server.apps.assets.models import Asset  # noqa: PLC0415
    from server.apps.clips.models import ClipCandidate  # noqa: PLC0415

    candidate = ClipCandidate.objects.select_related(
        'layout_config',
        'style_config',
        'run',
    ).get(id=candidate_id)

    if _preview_already_ready(candidate_id, candidate):
        logger.info(
            'clip_preview_skipped_already_ready',
            candidate_id=candidate_id,
        )
        return
    if not _try_claim_preview_worker(candidate_id):
        logger.info(
            'clip_preview_skipped_worker_claim',
            candidate_id=candidate_id,
        )
        return

    run_id = str(candidate.run_id)
    source_asset_id = get_run_source_asset_id(run_id)
    manifest_asset_id = get_run_manifest_asset_id(run_id)
    if source_asset_id is None:
        _set_preview_failed(candidate_id, 'Source video is not ready yet.')
        cache.delete(preview_worker_lock_key(candidate_id))
        return
    if manifest_asset_id is None:
        _set_preview_failed(candidate_id, 'Transcript is not ready yet.')
        cache.delete(preview_worker_lock_key(candidate_id))
        return

    timed_overlays = list(candidate.timed_overlays.all())
    source_asset = Asset.objects.get(id=uuid.UUID(source_asset_id))
    transcript_json = _load_transcript_json(manifest_asset_id)

    version = preview_config_version(candidate_id)
    cache.set(
        preview_cache_key(candidate_id),
        {'status': 'rendering', 'config_version': version},
        timeout=PREVIEW_CACHE_TIMEOUT,
    )

    try:
        rendered_bytes = _run_preview_pipeline(
            candidate=candidate,
            candidate_id=candidate_id,
            source_asset=source_asset,
            transcript_json=transcript_json,
            timed_overlays=timed_overlays,
        )
    except Exception as exc:
        logger.exception(
            'clip_preview_render_failed',
            candidate_id=candidate_id,
        )
        _set_preview_failed(candidate_id, str(exc))
        cache.delete(preview_worker_lock_key(candidate_id))
        return

    _persist_preview(candidate, candidate_id, rendered_bytes)
