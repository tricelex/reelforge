"""Route pipeline stage enqueues to the correct TaskIQ broker."""

from server.apps.pipelines.models import StageExecution
from server.apps.pipelines.tasks_api import advance_pipeline, execute_stage
from server.apps.pipelines.tasks_render import execute_render_stage
from server.common.queue_routing import physical_queue
from server.common.taskiq_sender import (
    kiq_api_task,
    kiq_api_task_async,
    kiq_render_task,
    kiq_render_task_async,
)


async def _logical_queue_for_execution(execution_id: str) -> str:
    queue = await StageExecution.objects.filter(
        pk=execution_id,
    ).values_list('queue', flat=True).afirst()
    return queue or 'api'


async def kiq_execute_stage_async(execution_id: str) -> None:
    """Enqueue execute_stage on the api or render broker."""
    logical = await _logical_queue_for_execution(execution_id)
    if physical_queue(logical) == 'render':
        await kiq_render_task_async(execute_render_stage, execution_id)
        return
    await kiq_api_task_async(execute_stage, execution_id)


def kiq_execute_stage(execution_id: str) -> None:
    """Enqueue execute_stage on the api or render broker (sync)."""
    queue = StageExecution.objects.filter(
        pk=execution_id,
    ).values_list('queue', flat=True).first()
    if physical_queue(queue or 'api') == 'render':
        kiq_render_task(execute_render_stage, execution_id)
        return
    kiq_api_task(execute_stage, execution_id)


def kiq_advance_pipeline(run_id: str) -> None:
    """Enqueue advance_pipeline on the api broker."""
    kiq_api_task(advance_pipeline, run_id)


async def kiq_advance_pipeline_async(run_id: str) -> None:
    """Enqueue advance_pipeline on the api broker."""
    await kiq_api_task_async(advance_pipeline, run_id)
