"""Executor helpers and core execute_stage_impl logic."""

import asyncio
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import django.utils.timezone as tz

from server.common.exceptions import FatalProviderError, RetryableProviderError

if TYPE_CHECKING:
    from server.apps.pipelines.models import StageExecution
    from server.apps.pipelines.stages.base import StageContext


async def kick_advance(execution: 'StageExecution') -> None:
    """Enqueue advance_pipeline for the run owning this execution."""
    from server.apps.pipelines.tasks import advance_pipeline  # noqa: PLC0415

    await advance_pipeline.kiq(str(execution.run_id))


async def execute_stage_kiq(execution_id: str) -> None:
    """Enqueue execute_stage (separate function for mockability in tests)."""
    from server.apps.pipelines.tasks import execute_stage  # noqa: PLC0415

    await execute_stage.kiq(execution_id)


async def _mark_running(execution: 'StageExecution') -> None:
    execution.status = 'RUNNING'
    execution.started_at = tz.now()
    await execution.asave(update_fields=['status', 'started_at'])


async def _complete(
    execution: 'StageExecution',
    output: dict,
    cost: Decimal = Decimal(0),
) -> None:
    execution.status = 'SUCCEEDED'
    execution.output = output
    execution.cost_usd = cost
    execution.finished_at = tz.now()
    await execution.asave(
        update_fields=['status', 'output', 'cost_usd', 'finished_at'],
    )


async def _fail(execution: 'StageExecution', error: Exception) -> None:
    execution.status = 'FAILED'
    execution.error = {
        'type': type(error).__name__,
        'message': str(error),
        'retryable': isinstance(error, RetryableProviderError),
    }
    execution.finished_at = tz.now()
    await execution.asave(update_fields=['status', 'error', 'finished_at'])


async def _mark_needs_input(
    execution: 'StageExecution', error: FatalProviderError,
) -> None:
    execution.status = 'NEEDS_INPUT'
    execution.error = {
        'type': type(error).__name__,
        'message': str(error),
        'retryable': False,
    }
    execution.finished_at = tz.now()
    await execution.asave(update_fields=['status', 'error', 'finished_at'])


async def _schedule_retry(
    execution: 'StageExecution', error: Exception,
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


async def _run_stage(
    execution: 'StageExecution',
    stage_cls: type,
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


async def execute_stage_impl(execution_id: str) -> None:
    """Core executor: idempotency check -> run -> retry/fatal/complete."""
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
            'upstream': ctx.upstream,
            'config': ctx.config,
            'prompt_snapshot': ctx.run.prompt_snapshot,
        })
        await execution.asave(update_fields=['input_hash'])

    cached = await find_cached_output(
        stage_key=execution.stage_key,
        shard_index=execution.shard_index,
        input_hash=execution.input_hash,
    )
    if cached is not None and cached.id != execution.id:
        await _complete(execution, cached.output, cost=Decimal(0))
        await kick_advance(execution)
        return

    await _run_stage(execution, stage_cls, ctx)
