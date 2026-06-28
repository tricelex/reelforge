"""DAG orchestrator: re-evaluate the graph and enqueue ready stages."""

import json
import uuid
from typing import TYPE_CHECKING, Any

import django.utils.timezone as tz
import structlog
from asgiref.sync import sync_to_async
from django.db import transaction

from server.apps.pipelines.logic.constants import (
    GATE_PARKED_STATUS,
    GATE_PARKED_STATUSES,
)
from server.common.redis_client import publish_pipeline_event

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from server.apps.pipelines.models import PipelineRun


async def publish_sse(run_id: str, data: dict[str, Any]) -> None:
    """Publish a JSON event to the pipeline Redis channel."""
    await publish_pipeline_event(run_id, json.dumps(data).encode())


async def execute_stage_kiq(execution_id: str) -> None:
    """Enqueue execute_stage (separate function for mockability in tests)."""
    from server.apps.pipelines.tasks import execute_stage  # noqa: PLC0415
    from server.common.taskiq_sender import kiq_task_async  # noqa: PLC0415

    await kiq_task_async(execute_stage, execution_id)


def _get_stage_states(run: 'PipelineRun') -> dict[str, str | None]:
    """Return the most-recent-attempt status per stage_key (top-level only)."""
    from server.apps.pipelines.models import StageExecution  # noqa: PLC0415

    result: dict[str, str | None] = {}
    qs = (
        StageExecution.objects
        .filter(run=run, parent=None)
        .order_by('stage_key', '-attempt')
        .only('stage_key', 'status', 'attempt')
    )
    for exec_ in qs:
        if exec_.stage_key not in result:
            result[exec_.stage_key] = exec_.status
    return result


def _eval_condition(node: dict[str, Any], run: 'PipelineRun') -> bool:
    """Evaluate a blueprint conditional string against run/channel state."""
    condition: str = node.get('conditional', '')
    if not condition:
        return True
    publish_mode = getattr(run.channel, 'publish_mode', None)
    if condition == "channel.publish_mode == 'review'":
        return publish_mode == 'review'
    if condition == "channel.publish_mode == 'auto'":
        return publish_mode == 'auto'
    return False


def _mark_skipped_sync(run: 'PipelineRun', stage_key: str) -> None:
    """Create a SKIPPED StageExecution for a gate or disabled conditional."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    StageExecution.objects.create(
        run=run,
        stage_key=stage_key,
        status=StageStatus.SKIPPED,
        input_hash='',
    )


def _park_gate_sync(run: 'PipelineRun', stage_key: str) -> None:
    """Park the run at AWAITING_REVIEW and open a gate StageExecution."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        RunStatus,
        StageExecution,
    )

    StageExecution.objects.create(
        run=run,
        stage_key=stage_key,
        status=GATE_PARKED_STATUS,
        input_hash='',
    )
    run.status = RunStatus.AWAITING_REVIEW
    run.save(update_fields=['status'])
    logger.info(
        'pipeline_gate_parked',
        run_id=str(run.id),
        gate_key=stage_key,
    )


def _create_queued_stage_sync(
    run: 'PipelineRun',
    node: dict[str, Any],
) -> str:
    """Create a QUEUED StageExecution; return its string ID."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.stages.base import (  # noqa: PLC0415
        STAGE_REGISTRY,
    )

    stage_cls = STAGE_REGISTRY[node['key']]
    exec_ = StageExecution.objects.create(
        run=run,
        stage_key=node['key'],
        status=StageStatus.QUEUED,
        queue=node.get('queue', stage_cls.queue),
        max_retries=stage_cls.max_retries,
        input_hash='',
    )
    return str(exec_.id)


def _gate_keys(graph: list[dict[str, Any]]) -> set[str]:
    return {node['key'] for node in graph if node.get('gate')}


def _has_parked_gate(
    states: dict[str, str | None],
    graph: list[dict[str, Any]],
) -> bool:
    """Return True when an armed gate stage is waiting for human approval."""
    for key in _gate_keys(graph):
        if states.get(key) in GATE_PARKED_STATUSES:
            return True
    return False


def _apply_terminal_status(
    run: 'PipelineRun',
    values: set[str],
    run_status: Any,
    stage_status: Any,
) -> None:
    """Apply FAILED, COMPLETED, or RUNNING to the run based on stage values."""
    terminal = {stage_status.SUCCEEDED, stage_status.SKIPPED}
    if stage_status.FAILED in values:
        run.status = run_status.FAILED
        run.finished_at = tz.now()
    elif all(s in terminal for s in values):
        run.status = run_status.COMPLETED
        run.finished_at = tz.now()
    elif stage_status.QUEUED in values or stage_status.RUNNING in values:
        if run.status == run_status.PENDING:
            run.status = run_status.RUNNING
            run.started_at = tz.now()


def _update_run_status_sync(
    run: 'PipelineRun',
    states: dict[str, str | None],
) -> None:
    """Transition run status based on current stage states (sync ORM)."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        RunStatus,
        StageStatus,
    )

    values = {s for s in states.values() if s is not None}
    if not values:
        return

    old_status = run.status
    graph: list[dict[str, Any]] = run.blueprint_snapshot.get('stages', [])
    if _has_parked_gate(states, graph):
        run.status = RunStatus.AWAITING_REVIEW
    else:
        _apply_terminal_status(run, values, RunStatus, StageStatus)
    if run.status != old_status or run.started_at is not None:
        run.save(update_fields=['status', 'started_at', 'finished_at'])


def _node_should_skip(
    node: dict[str, Any],
    run: 'PipelineRun',
    armed_gates: list[str],
) -> bool:
    """Return True if this node should be skipped."""
    if node.get('gate') and node['key'] not in armed_gates:
        return True
    return bool(node.get('conditional')) and not _eval_condition(node, run)


_TERMINAL_STAGE_STATES = frozenset({'SUCCEEDED', 'SKIPPED'})


def _deps_terminal(
    deps: list[str],
    states: dict[str, str | None],
    terminal: frozenset[str],
) -> bool:
    return all(states.get(dep) in terminal for dep in deps)


def _try_park_gate_sync(
    node: dict[str, Any],
    run: 'PipelineRun',
    states: dict[str, str | None],
    key: str,
) -> bool:
    """Park an armed gate when deps are terminal; return True if parked."""
    if not node.get('gate'):
        return False
    deps: list[str] = node.get('depends_on', [])
    if not _deps_terminal(deps, states, _TERMINAL_STAGE_STATES):
        return False
    _park_gate_sync(run, key)
    states[key] = GATE_PARKED_STATUS
    return True


def _try_enqueue_stage_sync(
    node: dict[str, Any],
    run: 'PipelineRun',
    states: dict[str, str | None],
    to_enqueue: list[str],
    key: str,
) -> None:
    """Enqueue a stage when dependencies are terminal."""
    from server.apps.pipelines.models import StageStatus  # noqa: PLC0415
    from server.apps.pipelines.stages.base import (  # noqa: PLC0415
        STAGE_REGISTRY,
    )

    if key not in STAGE_REGISTRY:
        logger.warning(
            'pipeline_stage_not_registered',
            run_id=str(run.id),
            stage_key=key,
        )
        return
    deps: list[str] = node.get('depends_on', [])
    if not _deps_terminal(deps, states, _TERMINAL_STAGE_STATES):
        return
    exec_id = _create_queued_stage_sync(run, node)
    to_enqueue.append(exec_id)
    states[key] = StageStatus.QUEUED


def _process_node_sync(
    node: dict[str, Any],
    run: 'PipelineRun',
    states: dict[str, str | None],
    armed_gates: list[str],
    to_enqueue: list[str],
) -> None:
    """Evaluate one blueprint node; enqueue, skip, or ignore (sync)."""
    from server.apps.pipelines.models import StageStatus  # noqa: PLC0415

    key = node['key']
    current = states.get(key)
    if current not in {None, StageStatus.PENDING}:
        return

    if _node_should_skip(node, run, armed_gates):
        _mark_skipped_sync(run, key)
        states[key] = StageStatus.SKIPPED
        return

    if _try_park_gate_sync(node, run, states, key):
        return

    _try_enqueue_stage_sync(node, run, states, to_enqueue, key)


def _resolve_armed_gates(
    run: 'PipelineRun',
    graph: list[dict[str, Any]],
    pipeline_kind: str,
) -> list[str]:
    """Return the list of gate keys that are armed for this run.

    CLIPPING pipelines always arm every gate node so the approval gate
    is never accidentally skipped by an empty channel.gates list.
    """
    gates: list[str] = list(getattr(run.channel, 'gates', None) or [])
    if pipeline_kind == 'CLIPPING':
        for node in graph:
            if node.get('gate') and node['key'] not in gates:
                gates.append(node['key'])
    return gates


def _advance_in_transaction(
    run_id: str,
) -> tuple[list[str], dict[str, str | None]]:
    """Run DAG evaluation inside a transaction with SELECT FOR UPDATE (sync).

    Returns (to_enqueue, states) to be processed after the transaction.
    """
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineRun,
        RunStatus,
    )

    to_enqueue: list[str] = []
    states: dict[str, str | None] = {}

    with transaction.atomic():
        run = (
            PipelineRun.objects
            .select_for_update()
            .select_related('channel', 'blueprint')
            .get(id=uuid.UUID(run_id))
        )
        if run.status in {
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.COMPLETED,
        }:
            return to_enqueue, states

        if run.is_paused:
            return to_enqueue, states

        graph: list[dict[str, Any]] = run.blueprint_snapshot.get('stages', [])
        states = _get_stage_states(run)
        armed_gates = _resolve_armed_gates(run, graph, run.blueprint.kind)

        for node in graph:
            _process_node_sync(
                node,
                run,
                states,
                armed_gates,
                to_enqueue,
            )

        _update_run_status_sync(run, states)

    return to_enqueue, states


_advance_in_transaction_async = sync_to_async(_advance_in_transaction)


def _approve_gate_sync(
    run_id: str,
    gate_key: str,
    output: dict[str, Any],
) -> None:
    """Mark gate SUCCEEDED and resume the run (sync wrapper)."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineRun,
        RunStatus,
        StageExecution,
        StageStatus,
    )

    with transaction.atomic():
        run = (
            PipelineRun.objects
            .select_for_update()
            .select_related('channel')
            .get(id=uuid.UUID(run_id))
        )
        execution = StageExecution.objects.select_for_update().get(
            run=run,
            stage_key=gate_key,
            parent=None,
            status__in=GATE_PARKED_STATUSES,
        )
        execution.status = StageStatus.SUCCEEDED
        execution.output = output
        execution.finished_at = tz.now()
        execution.save(update_fields=['status', 'output', 'finished_at'])

        run.status = RunStatus.RUNNING
        run.save(update_fields=['status'])


_approve_gate_sync_async = sync_to_async(_approve_gate_sync)


async def approve_gate_impl(
    run_id: str,
    gate_key: str,
    output: dict[str, Any],
) -> None:
    """Public async entry point: approve a gate and re-evaluate the DAG."""
    await _approve_gate_sync_async(run_id, gate_key, output)
    await advance_pipeline_impl(run_id)


def _get_failed_stage_summaries(run_id: str) -> list[dict[str, Any]]:
    """Return latest failure details per stage_key for logging."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    failures: list[dict[str, Any]] = []
    seen: set[str] = set()
    qs = StageExecution.objects.filter(
        run_id=run_id,
        parent=None,
        status=StageStatus.FAILED,
    ).order_by('stage_key', '-attempt')
    for exec_ in qs:
        if exec_.stage_key in seen:
            continue
        seen.add(exec_.stage_key)
        err = exec_.error or {}
        failures.append({
            'stage_key': exec_.stage_key,
            'attempt': exec_.attempt,
            'type': err.get('type'),
            'message': err.get('message'),
        })
    return failures


_get_failed_stage_summaries_async = sync_to_async(
    _get_failed_stage_summaries,
    thread_sensitive=True,
)


async def advance_pipeline_impl(run_id: str) -> None:
    """Re-evaluate the DAG and enqueue any newly-ready stages.

    Called at run start and after every stage terminal event.
    The inner DAG evaluation runs in a sync thread with SELECT FOR UPDATE.
    """
    to_enqueue, states = await _advance_in_transaction_async(run_id)

    log_kwargs: dict[str, Any] = {
        'run_id': run_id,
        'enqueued_count': len(to_enqueue),
        'states': dict(states),
    }
    if 'FAILED' in states.values():
        log_kwargs['failures'] = await _get_failed_stage_summaries_async(run_id)

    logger.info('pipeline_advanced', **log_kwargs)

    for exec_id in to_enqueue:
        await execute_stage_kiq(exec_id)

    await publish_sse(run_id, {'type': 'run.advanced', 'states': dict(states)})


def _downstream_stage_keys(
    graph: list[dict[str, Any]],
    stage_key: str,
) -> set[str]:
    """Return all stage keys that transitively depend on stage_key."""
    downstream: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in graph:
            deps = node.get('depends_on', [])
            key = node['key']
            if key in downstream:
                continue
            if stage_key in deps or any(d in downstream for d in deps):
                downstream.add(key)
                changed = True
    return downstream


def _cancel_run_sync(run_id: str) -> None:
    """Mark run and active stages as cancelled."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineRun,
        RunStatus,
        StageExecution,
        StageStatus,
    )

    active = {
        StageStatus.PENDING,
        StageStatus.QUEUED,
        StageStatus.RUNNING,
        StageStatus.NEEDS_INPUT,
    }
    with transaction.atomic():
        run = PipelineRun.objects.select_for_update().get(
            id=uuid.UUID(run_id),
        )
        if run.status in {RunStatus.COMPLETED, RunStatus.CANCELLED}:
            return
        StageExecution.objects.filter(
            run=run,
            status__in=active,
        ).update(status=StageStatus.CANCELLED)
        run.status = RunStatus.CANCELLED
        run.is_paused = False
        run.finished_at = tz.now()
        run.save(update_fields=['status', 'is_paused', 'finished_at'])


_cancel_run_sync_async = sync_to_async(_cancel_run_sync)


async def cancel_run_impl(run_id: str) -> None:
    """Cancel a pipeline run."""
    await _cancel_run_sync_async(run_id)
    await publish_sse(run_id, {'type': 'run.cancelled'})


def _pause_run_sync(run_id: str) -> None:
    """Set is_paused on the run."""
    from server.apps.pipelines.models import PipelineRun  # noqa: PLC0415

    with transaction.atomic():
        run = PipelineRun.objects.select_for_update().get(
            id=uuid.UUID(run_id),
        )
        run.is_paused = True
        run.save(update_fields=['is_paused'])


_pause_run_sync_async = sync_to_async(_pause_run_sync)


async def pause_run_impl(run_id: str) -> None:
    """Pause a pipeline run."""
    await _pause_run_sync_async(run_id)
    await publish_sse(run_id, {'type': 'run.paused'})


def _resume_run_sync(run_id: str) -> None:
    """Clear is_paused and set run back to RUNNING if needed."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineRun,
        RunStatus,
    )

    with transaction.atomic():
        run = PipelineRun.objects.select_for_update().get(
            id=uuid.UUID(run_id),
        )
        run.is_paused = False
        if run.status in {
            RunStatus.PENDING,
            RunStatus.AWAITING_REVIEW,
            RunStatus.BUDGET_HOLD,
        }:
            run.status = RunStatus.RUNNING
        run.save(update_fields=['is_paused', 'status'])


_resume_run_sync_async = sync_to_async(_resume_run_sync)


async def resume_run_impl(run_id: str) -> None:
    """Resume a paused pipeline run."""
    await _resume_run_sync_async(run_id)
    await advance_pipeline_impl(run_id)


def _rerun_stage_sync(
    run_id: str,
    stage_key: str,
    shard_indices: list[int] | None,
) -> list[str]:
    """Stale downstream stages and queue fresh attempts; return exec IDs."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineRun,
        RunStatus,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.stages.base import (  # noqa: PLC0415
        STAGE_REGISTRY,
    )

    to_enqueue: list[str] = []
    terminal = {
        StageStatus.SUCCEEDED,
        StageStatus.FAILED,
        StageStatus.NEEDS_INPUT,
        StageStatus.SKIPPED,
    }

    with transaction.atomic():
        run = (
            PipelineRun.objects
            .select_for_update()
            .select_related('channel')
            .get(id=uuid.UUID(run_id))
        )
        graph: list[dict[str, Any]] = run.blueprint_snapshot.get('stages', [])
        downstream = _downstream_stage_keys(graph, stage_key)
        stale_keys = downstream | {stage_key}

        StageExecution.objects.filter(
            run=run,
            stage_key__in=stale_keys,
            status__in=terminal,
        ).update(status=StageStatus.STALE)

        node = next((n for n in graph if n['key'] == stage_key), None)
        if node is None:
            return to_enqueue

        stage_cls = STAGE_REGISTRY.get(stage_key)
        if stage_cls is None:
            return to_enqueue

        qs = StageExecution.objects.filter(
            run=run,
            stage_key=stage_key,
            parent=None,
        )
        if shard_indices is not None:
            qs = qs.filter(shard_index__in=shard_indices)
        else:
            qs = qs.filter(shard_index__isnull=True)

        latest_attempt = (
            qs
            .order_by('-attempt')
            .values_list(
                'attempt',
                flat=True,
            )
            .first()
        )
        next_attempt = (latest_attempt or -1) + 1

        exec_ = StageExecution.objects.create(
            run=run,
            stage_key=stage_key,
            status=StageStatus.QUEUED,
            queue=node.get('queue', stage_cls.queue),
            max_retries=stage_cls.max_retries,
            attempt=next_attempt,
            input_hash='',
        )
        to_enqueue.append(str(exec_.id))

        run.status = RunStatus.RUNNING
        run.is_paused = False
        run.finished_at = None
        run.save(update_fields=['status', 'is_paused', 'finished_at'])

    return to_enqueue


_rerun_stage_sync_async = sync_to_async(_rerun_stage_sync)


async def rerun_stage_impl(
    run_id: str,
    stage_key: str,
    *,
    shard_indices: list[int] | None = None,
) -> None:
    """Rerun a stage and enqueue its new execution."""
    to_enqueue = await _rerun_stage_sync_async(
        run_id,
        stage_key,
        shard_indices,
    )
    for exec_id in to_enqueue:
        await execute_stage_kiq(exec_id)
    await publish_sse(
        run_id,
        {'type': 'stage.rerun', 'stage_key': stage_key},
    )
