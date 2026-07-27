"""TaskIQ broker tasks for pipeline execution (re-exports for compatibility)."""

from server.apps.generation.clients import youtube as yt_client
from server.apps.pipelines.tasks_api import (  # noqa: F401
    _apply_thumbnail_swap,
    _channel_median_ctr,
    _download_thumbnail_bytes,
    _maybe_swap_job,
    _next_untested_candidate,
    advance_pipeline,
    execute_stage,
    resume_publish_held_runs,
    swap_underperforming_thumbnails,
)
from server.apps.pipelines.tasks_render import execute_render_stage  # noqa: F401
