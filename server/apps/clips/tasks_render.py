"""Background render-queue tasks for the clips app."""

from asgiref.sync import sync_to_async

from server.apps.clips.export_render import render_clip_export_sync
from server.apps.clips.preview_render import render_clip_preview_sync
from server.common.broker import render_broker


@render_broker.task(retry_on_error=False)
async def render_clip_preview_task(candidate_id: str) -> None:
    """Render a lightweight editor preview for one clip candidate."""
    await sync_to_async(render_clip_preview_sync)(candidate_id)


@render_broker.task(retry_on_error=False)
async def render_clip_export_task(candidate_id: str) -> None:
    """Render a full-quality export for one clip candidate."""
    await sync_to_async(render_clip_export_sync)(candidate_id)


def _reset_smart_crop_sync(candidate_id: str) -> None:
    """Apply MediaPipe smart-crop detection for one candidate."""
    from server.apps.clips.services import ClipsService  # noqa: PLC0415
    from server.common.container import container  # noqa: PLC0415

    container.resolve(ClipsService).apply_smart_crop_detection(candidate_id)


@render_broker.task(retry_on_error=False)
async def reset_smart_crop_task(candidate_id: str) -> None:
    """Worker task: re-detect speaker framing after layout smart-crop reset."""
    await sync_to_async(_reset_smart_crop_sync)(candidate_id)
