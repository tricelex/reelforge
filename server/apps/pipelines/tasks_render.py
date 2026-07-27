"""TaskIQ render-queue tasks for pipeline execution."""

from server.common.broker import render_broker


@render_broker.task(retry_on_error=False)
async def execute_render_stage(execution_id: str) -> None:
    """Execute one render-queue pipeline stage (ffmpeg, etc.)."""
    from server.apps.pipelines.services.executor import (  # noqa: PLC0415
        execute_stage_impl,
    )

    await execute_stage_impl(execution_id)
