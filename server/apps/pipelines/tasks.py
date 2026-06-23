"""TaskIQ broker tasks for pipeline execution."""

from server.common.broker import broker


@broker.task(retry_on_error=False, queue='api')
async def execute_stage(execution_id: str) -> None:
    """Execute one pipeline stage; manages its own retry logic."""
    from server.apps.pipelines.services.executor import (  # noqa: PLC0415
        execute_stage_impl,
    )

    await execute_stage_impl(execution_id)


@broker.task(retry_on_error=False, queue='orchestrator')
async def advance_pipeline(run_id: str) -> None:
    """Re-evaluate the DAG and enqueue any newly-ready stages."""
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        advance_pipeline_impl,
    )

    await advance_pipeline_impl(run_id)
