"""Background tasks for the clips app."""

import uuid

import structlog
from asgiref.sync import sync_to_async

from server.apps.clips.export_render import render_clip_export_sync
from server.apps.clips.logic.constants import ClipSourceStatus, ClipSourceType
from server.apps.clips.models import ClipSource
from server.apps.clips.preview_render import render_clip_preview_sync
from server.apps.clips.source_probe import probe_youtube_or_rss
from server.common.broker import broker

logger = structlog.get_logger(__name__)


def _probe_clip_source_sync(source_id: str) -> None:
    """Probe one clip source and update status."""
    source = ClipSource.objects.get(id=uuid.UUID(source_id))
    if source.source_type not in (
        ClipSourceType.YOUTUBE,
        ClipSourceType.RSS,
    ):
        return
    try:
        info = probe_youtube_or_rss(source.url)
        source.title = info['title'] or source.title
        source.duration_sec = info['duration_sec'] or None
        source.status = ClipSourceStatus.READY
        source.error_message = ''
        source.save(
            update_fields=[
                'title',
                'duration_sec',
                'status',
                'error_message',
                'updated_at',
            ],
        )
        if source.auto_start:
            from server.apps.clips.source_services import (  # noqa: PLC0415
                _maybe_auto_start_run,
            )

            _maybe_auto_start_run(source)
    except Exception as exc:
        logger.exception('clip_source_probe_failed', source_id=source_id)
        source.status = ClipSourceStatus.FAILED
        source.error_message = str(exc)[:500]
        source.save(
            update_fields=['status', 'error_message', 'updated_at'],
        )


@broker.task(retry_on_error=False, queue='api')
async def probe_clip_source_task(source_id: str) -> None:
    """Async wrapper for clip source metadata probe."""
    await sync_to_async(_probe_clip_source_sync)(source_id)


@broker.task(retry_on_error=False, queue='render')
async def render_clip_preview_task(candidate_id: str) -> None:
    """Render a lightweight editor preview for one clip candidate."""
    await sync_to_async(render_clip_preview_sync)(candidate_id)


@broker.task(retry_on_error=False, queue='render')
async def render_clip_export_task(candidate_id: str) -> None:
    """Render a full-quality export for one clip candidate."""
    await sync_to_async(render_clip_export_sync)(candidate_id)


def _reset_smart_crop_sync(candidate_id: str) -> None:
    """Apply MediaPipe smart-crop detection for one candidate."""
    from server.apps.clips.services import ClipsService  # noqa: PLC0415
    from server.common.container import container  # noqa: PLC0415

    container.resolve(ClipsService).apply_smart_crop_detection(candidate_id)


@broker.task(retry_on_error=False, queue='render')
async def reset_smart_crop_task(candidate_id: str) -> None:
    """Worker task: re-detect speaker framing after layout smart-crop reset."""
    await sync_to_async(_reset_smart_crop_sync)(candidate_id)
