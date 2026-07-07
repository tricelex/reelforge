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


@broker.task(retry_on_error=False, queue='api')
async def resume_publish_held_runs() -> None:
    """Resume every PUBLISH_HOLD run — called once daily by a scheduler.

    Uses ``resume_run_impl`` (not ``advance_pipeline_impl``) so the run
    transitions out of PUBLISH_HOLD back to RUNNING before the DAG is
    re-evaluated; a run still over its daily cap re-parks at PUBLISH_HOLD.
    """
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineRun,
        RunStatus,
    )
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        resume_run_impl,
    )

    run_ids = [
        str(run_id)
        async for run_id in PipelineRun.objects.filter(
            status=RunStatus.PUBLISH_HOLD,
        ).values_list('id', flat=True)
    ]
    for run_id in run_ids:
        await resume_run_impl(run_id)
