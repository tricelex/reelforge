"""Executor helpers and core execute_stage_impl logic."""

import asyncio
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import django.utils.timezone as tz
import structlog
from asgiref.sync import sync_to_async
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from server.common.exceptions import FatalProviderError, RetryableProviderError

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from server.apps.pipelines.models import StageExecution
    from server.apps.pipelines.stages.base import Stage, StageContext


async def advance_pipeline_kiq(run_id: str) -> None:
    """Enqueue advance_pipeline task."""
    from server.apps.pipelines.tasks import advance_pipeline  # noqa: PLC0415
    from server.common.taskiq_sender import kiq_task_async  # noqa: PLC0415

    await kiq_task_async(advance_pipeline, run_id)


async def kick_advance(execution: 'StageExecution') -> None:
    """Re-evaluate the DAG. For child shards, update parent first."""
    if execution.parent_id is not None:
        await _maybe_complete_fan_out_parent(execution)
    else:
        await advance_pipeline_kiq(str(execution.run_id))


async def execute_stage_kiq(execution_id: str) -> None:
    """Enqueue execute_stage (separate function for mockability in tests)."""
    from server.apps.pipelines.tasks import execute_stage  # noqa: PLC0415
    from server.common.taskiq_sender import kiq_task_async  # noqa: PLC0415

    await kiq_task_async(execute_stage, execution_id)


def _execution_log_fields(execution: 'StageExecution') -> dict[str, Any]:
    return {
        'run_id': str(execution.run_id),
        'execution_id': str(execution.id),
        'stage_key': execution.stage_key,
        'attempt': execution.attempt,
    }


def _cache_log_fields(
    execution: 'StageExecution',
    cached_execution: 'StageExecution',
) -> dict[str, Any]:
    log_fields = _execution_log_fields(execution)
    log_fields['cached_execution_id'] = str(cached_execution.id)
    log_fields['cached_run_id'] = str(cached_execution.run_id)
    log_fields['is_fan_out_child'] = execution.parent_id is not None
    return log_fields


async def _mark_running(execution: 'StageExecution') -> None:
    execution.status = 'RUNNING'
    execution.started_at = tz.now()
    await execution.asave(update_fields=['status', 'started_at'])
    logger.info('stage_started', **_execution_log_fields(execution))


async def _complete(
    execution: 'StageExecution',
    output: dict[str, Any],
    cost: Decimal = Decimal(0),
) -> None:
    execution.status = 'SUCCEEDED'
    execution.output = output
    execution.cost_usd = cost
    execution.finished_at = tz.now()
    await execution.asave(
        update_fields=['status', 'output', 'cost_usd', 'finished_at'],
    )
    logger.info('stage_succeeded', **_execution_log_fields(execution))


async def _fail(execution: 'StageExecution', error: Exception) -> None:
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        publish_sse,
    )

    execution.status = 'FAILED'
    execution.error = {
        'type': type(error).__name__,
        'message': str(error),
        'retryable': isinstance(error, RetryableProviderError),
    }
    execution.finished_at = tz.now()
    await execution.asave(update_fields=['status', 'error', 'finished_at'])

    log_fields = _execution_log_fields(execution)
    log_fields['error'] = execution.error
    logger.error('stage_failed', **log_fields)

    span = trace.get_current_span()
    span.record_exception(error)
    span.set_status(StatusCode.ERROR, str(error))

    await publish_sse(
        str(execution.run_id),
        {
            'type': 'stage.failed',
            'stage_key': execution.stage_key,
            'attempt': execution.attempt,
            'error_type': execution.error['type'],
            'error_message': execution.error['message'],
            'retryable': execution.error['retryable'],
        },
    )


async def _mark_needs_input(
    execution: 'StageExecution',
    error: FatalProviderError,
) -> None:
    from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
        publish_sse,
    )

    execution.status = 'NEEDS_INPUT'
    execution.error = {
        'type': type(error).__name__,
        'message': str(error),
        'retryable': False,
    }
    if getattr(error, 'error_code', None):
        execution.error['error_code'] = error.error_code
    update_fields = ['status', 'error', 'finished_at']
    if getattr(error, 'details', None):
        execution.output = error.details
        update_fields.append('output')
    execution.finished_at = tz.now()
    await execution.asave(update_fields=update_fields)

    log_fields = _execution_log_fields(execution)
    log_fields['error'] = execution.error
    logger.error('stage_needs_input', **log_fields)

    await publish_sse(
        str(execution.run_id),
        {
            'type': 'stage.needs_input',
            'stage_key': execution.stage_key,
            'attempt': execution.attempt,
            'error_type': execution.error['type'],
            'error_message': execution.error['message'],
            'retryable': False,
        },
    )


async def _schedule_retry(
    execution: 'StageExecution',
    error: Exception,
) -> None:
    """Mark this attempt FAILED and enqueue the next attempt."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    await _fail(execution, error)
    next_exec = await StageExecution.objects.acreate(
        run_id=execution.run_id,
        stage_key=execution.stage_key,
        parent=execution.parent,
        shard_index=execution.shard_index,
        attempt=execution.attempt + 1,
        max_retries=execution.max_retries,
        input_hash=execution.input_hash,
        input_snapshot=execution.input_snapshot,
        queue=execution.queue,
        status=StageStatus.QUEUED,
    )
    await execute_stage_kiq(str(next_exec.id))


async def _next_fan_out_child_attempt(
    run_id: uuid.UUID,
    stage_key: str,
    shard_index: int,
    parent_attempt: int,
) -> int:
    """Pick a child attempt that satisfies uq_stage_attempt for this shard."""
    from django.db.models import Max  # noqa: PLC0415

    from server.apps.pipelines.models import StageExecution  # noqa: PLC0415

    result = await StageExecution.objects.filter(
        run_id=run_id,
        stage_key=stage_key,
        shard_index=shard_index,
    ).aaggregate(m=Max('attempt'))
    max_existing = result['m']
    if max_existing is None:
        return parent_attempt
    return max(parent_attempt, max_existing + 1)


async def _handle_fan_out(
    parent: 'StageExecution',
    shard_inputs: list[dict[str, Any]],
) -> None:
    """Mark parent RUNNING, create QUEUED child executions, kick them."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    await _mark_running(parent)
    for i, shard_input in enumerate(shard_inputs):
        child_attempt = await _next_fan_out_child_attempt(
            parent.run_id,
            parent.stage_key,
            i,
            parent.attempt,
        )
        child = await StageExecution.objects.acreate(
            run_id=parent.run_id,
            stage_key=parent.stage_key,
            parent=parent,
            shard_index=i,
            attempt=child_attempt,
            status=StageStatus.QUEUED,
            queue=parent.queue,
            max_retries=parent.max_retries,
            input_snapshot=shard_input,
            input_hash='',
        )
        await execute_stage_kiq(str(child.id))


async def _maybe_complete_fan_out_parent(  # noqa: C901
    child: 'StageExecution',
) -> None:
    """After a child terminal event, update parent status if all shards done."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    parent_id = child.parent_id
    if parent_id is None:
        return
    parent = await StageExecution.objects.aget(id=parent_id)
    if parent.status in {StageStatus.SUCCEEDED, StageStatus.FAILED}:
        return

    shard_entries: dict[int, dict[str, Any]] = {}
    async for sib in StageExecution.objects.filter(parent=parent).order_by(
        'shard_index',
        '-attempt',
    ):
        if (
            sib.shard_index is not None
            and sib.shard_index not in shard_entries
        ):
            entry: dict[str, Any] = {
                'shard_index': sib.shard_index,
                'status': sib.status,
            }
            if sib.output:
                entry.update(sib.output)
            shard_entries[sib.shard_index] = entry

    terminal = {StageStatus.SUCCEEDED, StageStatus.SKIPPED}
    values = {entry['status'] for entry in shard_entries.values()}

    if all(s in terminal for s in values):
        parent.status = StageStatus.SUCCEEDED
        parent.output = {
            'shards': [
                shard_entries[idx] for idx in sorted(shard_entries)
            ],
        }
        parent.finished_at = tz.now()
        await parent.asave(update_fields=['status', 'output', 'finished_at'])
        await advance_pipeline_kiq(str(parent.run_id))
    elif (
        StageStatus.FAILED in values
        or StageStatus.NEEDS_INPUT in values
    ):
        in_flight = await StageExecution.objects.filter(
            parent=parent,
            status__in=[StageStatus.QUEUED, StageStatus.RUNNING],
        ).aexists()
        if not in_flight:
            if StageStatus.NEEDS_INPUT in values:
                parent.status = StageStatus.NEEDS_INPUT
                parent.error = {
                    'message': 'one or more shards need input',
                }
            else:
                parent.status = StageStatus.FAILED
                parent.error = {'message': 'one or more shards failed'}
            parent.finished_at = tz.now()
            await parent.asave(
                update_fields=['status', 'error', 'finished_at'],
            )
            await advance_pipeline_kiq(str(parent.run_id))


async def _run_stage(
    execution: 'StageExecution',
    stage_cls: 'type[Stage]',
    ctx: 'StageContext',
) -> None:
    """Run the stage and handle retryable/fatal/unexpected errors."""
    await _mark_running(execution)
    try:
        async with asyncio.timeout(stage_cls.timeout_s):
            output = await stage_cls().run(ctx)
        await _complete(execution, output, cost=ctx.costs.total_usd)
    except RetryableProviderError as exc:
        if execution.attempt < execution.max_retries:
            await _schedule_retry(execution, exc)
            return
        await _fail(execution, exc)
    except FatalProviderError as exc:
        await _mark_needs_input(execution, exc)
    except Exception as exc:
        await _fail(execution, exc)
    finally:
        await kick_advance(execution)


async def execute_stage_impl(execution_id: str) -> None:  # noqa: C901
    """Core executor: idempotency check, fan-out, run, retry/fatal handling."""
    from server.apps.pipelines.models import StageExecution  # noqa: PLC0415
    from server.apps.pipelines.services.context import (  # noqa: PLC0415
        build_context,
    )
    from server.apps.pipelines.services.idempotency import (  # noqa: PLC0415
        find_cached_output,
    )
    from server.apps.pipelines.stages.base import (  # noqa: PLC0415
        STAGE_REGISTRY,
        compute_input_hash,
    )

    execution = await StageExecution.objects.select_related('run').aget(
        id=uuid.UUID(execution_id),
    )
    stage_cls = STAGE_REGISTRY.get(execution.stage_key)
    if stage_cls is None:
        await _fail(
            execution,
            RuntimeError(f'Unknown stage key: {execution.stage_key}'),
        )
        await kick_advance(execution)
        return

    ctx = await build_context(execution)

    if not execution.input_hash:
        execution.input_hash = compute_input_hash({
            'stage_key': execution.stage_key,
            'shard_index': execution.shard_index,
            'topic': ctx.run.topic,
            'blueprint_id': str(ctx.run.blueprint_id),
            'upstream': ctx.upstream,
            'config': ctx.config,
            'prompt_snapshot': ctx.run.prompt_snapshot,
            'input_snapshot': execution.input_snapshot,
        })
        await execution.asave(update_fields=['input_hash'])

    shard_inputs: list[dict[str, Any]] | None = None
    if execution.parent_id is None:
        shard_inputs = await sync_to_async(
            stage_cls().fan_out,
            thread_sensitive=True,
        )(ctx)

    if shard_inputs is None:
        cached = await find_cached_output(
            run_id=execution.run_id,
            stage_key=execution.stage_key,
            shard_index=execution.shard_index,
            input_hash=execution.input_hash,
        )
        if cached is not None and cached.id != execution.id:
            logger.info(
                'stage_cache_hit',
                **_cache_log_fields(execution, cached),
            )
            await _complete(execution, cached.output, cost=Decimal(0))
            await kick_advance(execution)
            return

    # Fan-out: only for top-level (non-child) executions
    if shard_inputs is not None:
        already_fanned = await StageExecution.objects.filter(
            parent=execution,
        ).aexists()
        if not already_fanned:
            if not shard_inputs:
                await _complete(execution, {'shards': []}, cost=Decimal(0))
                await kick_advance(execution)
            else:
                await _handle_fan_out(execution, shard_inputs)
        return

    await _run_stage(execution, stage_cls, ctx)
