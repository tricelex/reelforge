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
    from server.apps.pipelines.enqueue import (  # noqa: PLC0415
        kiq_execute_stage_async,
    )

    await kiq_execute_stage_async(execution_id)


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


def _promote_or_create_stage_sync(
    run: 'PipelineRun',
    stage_key: str,
    status: str,
) -> None:
    """Promote a PENDING row to *status*, or create with the next attempt.

    Rerun seeds PENDING downstream rows (including gates). Park/skip must
    reuse those rows — creating attempt=0 always collides with
    ``uq_stage_attempt`` when a PENDING/STALE row already exists.
    """
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    pending = (
        StageExecution.objects
        .filter(
            run=run,
            stage_key=stage_key,
            parent=None,
            status=StageStatus.PENDING,
        )
        .order_by('-attempt')
        .first()
    )
    if pending is not None:
        pending.status = status
        pending.save(update_fields=['status'])
        return

    StageExecution.objects.create(
        run=run,
        stage_key=stage_key,
        status=status,
        attempt=_next_stage_attempt(run, stage_key),
        input_hash='',
    )


def _mark_skipped_sync(run: 'PipelineRun', stage_key: str) -> None:
    """Create a SKIPPED StageExecution for a gate or disabled conditional."""
    from server.apps.pipelines.models import StageStatus  # noqa: PLC0415

    _promote_or_create_stage_sync(run, stage_key, StageStatus.SKIPPED)


def _park_gate_sync(run: 'PipelineRun', stage_key: str) -> None:
    """Park the run at AWAITING_REVIEW and open a gate StageExecution."""
    from server.apps.pipelines.models import RunStatus  # noqa: PLC0415

    _promote_or_create_stage_sync(run, stage_key, GATE_PARKED_STATUS)
    run.status = RunStatus.AWAITING_REVIEW
    run.save(update_fields=['status'])
    logger.info(
        'pipeline_gate_parked',
        run_id=str(run.id),
        gate_key=stage_key,
    )


def _next_stage_attempt(
    run: 'PipelineRun',
    stage_key: str,
    *,
    shard_index: int | None = None,
) -> int:
    """Return the next attempt number for a top-level or shard execution."""
    from server.apps.pipelines.models import StageExecution  # noqa: PLC0415

    qs = StageExecution.objects.filter(
        run=run,
        stage_key=stage_key,
        shard_index=shard_index,
    )
    if shard_index is None:
        qs = qs.filter(parent=None)
    latest = qs.order_by('-attempt').values_list('attempt', flat=True).first()
    return (latest if latest is not None else -1) + 1


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
        attempt=_next_stage_attempt(run, node['key']),
        input_hash='',
    )
    return str(exec_.id)


def _seed_pending_downstream_sync(
    run: 'PipelineRun',
    graph: list[dict[str, Any]],
    downstream_keys: set[str],
) -> None:
    """Create PENDING attempts for downstream keys after an explicit rerun.

    Scene-edit STALE markers intentionally do not call this — only
    ``_rerun_stage_sync`` seeds PENDING so advance can resume the DAG
    without auto-spending on storyboard text edits.
    """
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.stages.base import (  # noqa: PLC0415
        STAGE_REGISTRY,
    )

    for key in sorted(downstream_keys):
        node = next((n for n in graph if n['key'] == key), None)
        if node is None:
            continue
        stage_cls = STAGE_REGISTRY.get(key)
        if stage_cls is None:
            continue
        StageExecution.objects.create(
            run=run,
            stage_key=key,
            status=StageStatus.PENDING,
            queue=node.get('queue', stage_cls.queue),
            max_retries=stage_cls.max_retries,
            attempt=_next_stage_attempt(run, key),
            input_hash='',
        )


def _gate_keys(graph: list[dict[str, Any]]) -> set[str]:
    return {node['key'] for node in graph if node.get('gate')}


def _has_parked_gate(
    states: dict[str, str | None],
    graph: list[dict[str, Any]],
) -> bool:
    """Return True when a gate is waiting for human approval (NEEDS_INPUT).

    Auto character_gate claims use RUNNING for in-flight fal work — that is
    not a human park, so it must not flip the run to AWAITING_REVIEW.
    """
    for key in _gate_keys(graph):
        if states.get(key) == GATE_PARKED_STATUS:
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
    in_flight = (
        stage_status.QUEUED in values or stage_status.RUNNING in values
    )
    if stage_status.FAILED in values:
        run.status = run_status.FAILED
        run.finished_at = tz.now()
        return
    if stage_status.NEEDS_INPUT in values and not in_flight:
        # Non-gate creative/QC fatals park the run for operator action.
        run.status = run_status.AWAITING_REVIEW
        return
    if all(s in terminal for s in values):
        run.status = run_status.COMPLETED
        run.finished_at = tz.now()
        return
    if in_flight and run.status in {
        run_status.PENDING,
        run_status.AWAITING_REVIEW,
    }:
        run.status = run_status.RUNNING
        if run.started_at is None:
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
        # Auto mode still evaluates character_gate so Studio can run.
        if (
            node['key'] == 'character_gate'
            and getattr(run.channel, 'character_design_mode', None) == 'auto'
        ):
            return False
        return True
    return bool(node.get('conditional')) and not _eval_condition(node, run)


# Sentinel recorded in `states` for a rate-limited 'publish' node. Not a real
# StageStatus value (no StageExecution row is created) — it only exists so
# _update_run_status_sync's terminal-status recompute doesn't see the node as
# absent (which would look like "no dependency left, run must be COMPLETE")
# and overwrite the PUBLISH_HOLD status that was just set on the run.
_PUBLISH_HOLD_STATE_SENTINEL = 'PUBLISH_HOLD_PENDING'


def _publish_rate_limited(run: 'PipelineRun') -> bool:
    """True when the channel already hit its max_publishes_per_day today."""
    from server.apps.publishing.models import (  # noqa: PLC0415
        PublishJob,
        PublishStatus,
    )

    channel = run.channel
    cap = channel.max_publishes_per_day
    if not cap:
        return False
    today_start = tz.now().replace(hour=0, minute=0, second=0, microsecond=0)
    published_today = PublishJob.objects.filter(
        channel=channel,
        status=PublishStatus.COMPLETED,
        created_at__gte=today_start,
    ).count()
    return published_today >= cap


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
    """Park an armed gate when deps are terminal; return True if handled."""
    if not node.get('gate'):
        return False
    deps: list[str] = node.get('depends_on', [])
    if not _deps_terminal(deps, states, _TERMINAL_STAGE_STATES):
        return False
    if _auto_approve_clip_gate(run, key, states):
        return True
    if _handle_character_gate_sync(run, key, states):
        return True
    _park_gate_sync(run, key)
    states[key] = GATE_PARKED_STATUS
    return True


def _latest_stage_output(run: 'PipelineRun', stage_key: str) -> dict[str, Any]:
    """Return output dict for the latest parent execution of stage_key."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    row = (
        StageExecution.objects
        .filter(
            run=run,
            stage_key=stage_key,
            parent=None,
            status=StageStatus.SUCCEEDED,
        )
        .order_by('-attempt', '-created_at')
        .first()
    )
    if row is None or not isinstance(row.output, dict):
        return {}
    return dict(row.output)


def _succeed_gate_sync(
    run: 'PipelineRun',
    key: str,
    states: dict[str, str | None],
    output: dict[str, Any],
) -> None:
    """Mark a gate SUCCEEDED with output and update in-memory states."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    StageExecution.objects.create(
        run=run,
        stage_key=key,
        status=StageStatus.SUCCEEDED,
        input_hash='',
        output=output,
        finished_at=tz.now(),
    )
    states[key] = StageStatus.SUCCEEDED


def _handle_character_gate_sync(
    run: 'PipelineRun',
    key: str,
    states: dict[str, str | None],
) -> bool:
    """Skip, auto-design, or defer park for character_gate; True if handled."""
    if key != 'character_gate':
        return False

    from server.apps.channels.models import (  # noqa: PLC0415
        CharacterDesignMode,
    )

    proposal = _latest_stage_output(run, 'cast_proposal')
    requires = bool(proposal.get('requires_character_design'))
    mode = getattr(
        run.channel,
        'character_design_mode',
        CharacterDesignMode.INTERACTIVE,
    )

    if not requires:
        _succeed_gate_sync(
            run,
            key,
            states,
            {
                'skipped_reason': 'no_characters',
                'reason': proposal.get('reason', ''),
            },
        )
        logger.info(
            'pipeline_character_gate_skipped',
            run_id=str(run.id),
            reason='no_characters',
        )
        return True

    if mode == CharacterDesignMode.NONE:
        _succeed_gate_sync(
            run,
            key,
            states,
            {'skipped_reason': 'mode_none'},
        )
        logger.info(
            'pipeline_character_gate_skipped',
            run_id=str(run.id),
            reason='mode_none',
        )
        return True

    if mode == CharacterDesignMode.AUTO:
        # Claim RUNNING inside the advance lock; fal work runs after commit
        # so we never hold SELECT FOR UPDATE across minutes of image gen,
        # and we never nest asyncio.run inside the worker event loop.
        _claim_auto_character_gate_sync(run, key, states)
        return True

    # interactive — caller parks when gate is armed
    return False


def _claim_auto_character_gate_sync(
    run: 'PipelineRun',
    key: str,
    states: dict[str, str | None],
) -> None:
    """Mark character_gate RUNNING so post-commit auto-design can finish it."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    latest = (
        StageExecution.objects
        .filter(run=run, stage_key=key, parent=None)
        .order_by('-attempt', '-created_at')
        .first()
    )
    if latest is not None and latest.status in {
        StageStatus.SUCCEEDED,
        StageStatus.RUNNING,
        StageStatus.FAILED,
        StageStatus.NEEDS_INPUT,
    }:
        states[key] = latest.status
        return

    StageExecution.objects.create(
        run=run,
        stage_key=key,
        status=StageStatus.RUNNING,
        input_hash='',
        started_at=tz.now(),
    )
    states[key] = StageStatus.RUNNING
    logger.info(
        'pipeline_character_gate_auto_claimed',
        run_id=str(run.id),
    )


def _finish_auto_character_gate_sync(run_id: str) -> bool:
    """Complete a RUNNING auto character_gate with Studio fal work.

    Returns True when a RUNNING claim was found and finalized (success or
    failure), so the caller can re-advance the DAG.
    """
    from server.apps.channels.models import (  # noqa: PLC0415
        CharacterDesignMode,
    )
    from server.apps.pipelines.models import (  # noqa: PLC0415
        PipelineRun,
        StageExecution,
        StageStatus,
    )
    from server.apps.pipelines.services.auto_character_design import (  # noqa: PLC0415
        run_auto_character_design,
    )

    run = (
        PipelineRun.objects
        .select_related('channel')
        .get(id=uuid.UUID(run_id))
    )
    if (
        getattr(run.channel, 'character_design_mode', None)
        != CharacterDesignMode.AUTO
    ):
        return False

    execution = (
        StageExecution.objects
        .filter(
            run=run,
            stage_key='character_gate',
            parent=None,
            status=StageStatus.RUNNING,
        )
        .order_by('-attempt', '-created_at')
        .first()
    )
    if execution is None:
        return False

    try:
        output = run_auto_character_design(run)
    except Exception as exc:
        execution.status = StageStatus.FAILED
        execution.error = {
            'type': type(exc).__name__,
            'message': str(exc),
            'retryable': True,
        }
        execution.finished_at = tz.now()
        execution.save(update_fields=['status', 'error', 'finished_at'])
        logger.exception(
            'pipeline_character_gate_auto_failed',
            run_id=run_id,
            error=execution.error,
        )
        return True

    execution.status = StageStatus.SUCCEEDED
    execution.output = output
    execution.finished_at = tz.now()
    execution.save(update_fields=['status', 'output', 'finished_at'])
    logger.info(
        'pipeline_character_gate_auto_succeeded',
        run_id=run_id,
        designed_count=len(output.get('designed', [])),
    )
    return True


def _auto_approve_clip_gate(
    run: 'PipelineRun',
    key: str,
    states: dict[str, str | None],
) -> bool:
    """Auto-complete clip approval when one-click mode is enabled.

    Marks proposed candidates approved, writes a succeeded gate execution,
    updates ``states`` so downstream render can enqueue in the same advance
    pass, and returns True when handled.
    """
    from server.apps.pipelines.models import StageStatus  # noqa: PLC0415

    if key != 'clip_approval_gate':
        return False
    clip_opts = (run.prompt_snapshot or {}).get('clip_options') or {}
    if not isinstance(clip_opts, dict) or not clip_opts.get('auto_approve'):
        return False

    from server.apps.clips.logic.constants import (  # noqa: PLC0415
        CandidateStatus,
    )
    from server.apps.clips.models import ClipCandidate  # noqa: PLC0415
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
    )

    candidates = list(
        ClipCandidate.objects.filter(
            run=run,
            status=CandidateStatus.PROPOSED,
        ).order_by('-virality_score', '-relevance_score'),
    )
    if not candidates:
        return False

    approved_ids = [str(c.id) for c in candidates]
    ClipCandidate.objects.filter(
        id__in=[c.id for c in candidates],
    ).update(status=CandidateStatus.APPROVED)
    StageExecution.objects.create(
        run=run,
        stage_key=key,
        status=StageStatus.SUCCEEDED,
        input_hash='',
        output={'approved_candidate_ids': approved_ids},
        finished_at=tz.now(),
    )
    states[key] = StageStatus.SUCCEEDED
    logger.info(
        'pipeline_gate_auto_approved',
        run_id=str(run.id),
        gate_key=key,
        candidate_count=len(approved_ids),
    )
    return True


def _try_enqueue_stage_sync(
    node: dict[str, Any],
    run: 'PipelineRun',
    states: dict[str, str | None],
    to_enqueue: list[str],
    key: str,
) -> None:
    """Enqueue a stage when dependencies are terminal."""
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )
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

    pending = (
        StageExecution.objects
        .filter(
            run=run,
            stage_key=key,
            parent=None,
            status=StageStatus.PENDING,
        )
        .order_by('-attempt')
        .first()
    )
    if pending is not None:
        pending.status = StageStatus.QUEUED
        pending.save(update_fields=['status'])
        to_enqueue.append(str(pending.id))
        states[key] = StageStatus.QUEUED
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
    from server.apps.pipelines.models import (  # noqa: PLC0415
        RunStatus,
        StageStatus,
    )

    key = node['key']
    current = states.get(key)
    if current not in {None, StageStatus.PENDING}:
        return

    if _node_should_skip(node, run, armed_gates):
        # Wait for depends_on before auto-skipping — otherwise downstream
        # stages that only depend on this gate enqueue with empty upstream.
        deps: list[str] = node.get('depends_on', [])
        if not _deps_terminal(deps, states, _TERMINAL_STAGE_STATES):
            return
        _mark_skipped_sync(run, key)
        states[key] = StageStatus.SKIPPED
        return

    if key == 'publish' and _publish_rate_limited(run):
        run.status = RunStatus.PUBLISH_HOLD
        run.save(update_fields=['status'])
        states[key] = _PUBLISH_HOLD_STATE_SENTINEL
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


def _over_budget(run: 'PipelineRun') -> bool:
    """True when the channel has a spend cap and the run has hit it."""
    cap = run.channel.default_budget_usd
    return cap is not None and run.total_cost_usd >= cap


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

        if run.status == RunStatus.BUDGET_HOLD:
            return to_enqueue, states

        if _over_budget(run):
            run.status = RunStatus.BUDGET_HOLD
            run.save(update_fields=['status'])
            logger.info(
                'pipeline_budget_hold',
                run_id=str(run.id),
                spent_usd=str(run.total_cost_usd),
                budget_usd=str(run.channel.default_budget_usd),
            )
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
    from django.core.exceptions import ValidationError  # noqa: PLC0415

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
        try:
            execution = StageExecution.objects.select_for_update().get(
                run=run,
                stage_key=gate_key,
                parent=None,
                status__in=GATE_PARKED_STATUSES,
            )
        except StageExecution.DoesNotExist as exc:
            msg = f'No parked gate "{gate_key}" for this run'
            raise ValidationError(msg) from exc
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


async def advance_pipeline_impl(
    run_id: str,
    *,
    _auto_design_depth: int = 0,
) -> None:
    """Re-evaluate the DAG and enqueue any newly-ready stages.

    Called at run start and after every stage terminal event.
    The inner DAG evaluation runs in a sync thread with SELECT FOR UPDATE.
    Auto character design (fal) runs after that transaction commits.
    """
    from server.apps.pipelines.models import StageStatus  # noqa: PLC0415

    to_enqueue, states = await _advance_in_transaction_async(run_id)

    log_kwargs: dict[str, Any] = {
        'run_id': run_id,
        'enqueued_count': len(to_enqueue),
        'states': dict(states),
    }
    if 'FAILED' in states.values():
        log_kwargs['failures'] = await _get_failed_stage_summaries_async(run_id)

    logger.info('pipeline_advanced', **log_kwargs)

    if (
        states.get('character_gate') == StageStatus.RUNNING
        and _auto_design_depth < 1
    ):
        finished = await sync_to_async(_finish_auto_character_gate_sync)(
            run_id,
        )
        if finished:
            await advance_pipeline_impl(
                run_id,
                _auto_design_depth=_auto_design_depth + 1,
            )
            return

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
            RunStatus.PUBLISH_HOLD,
        }:
            run.status = RunStatus.RUNNING
        run.save(update_fields=['is_paused', 'status'])


_resume_run_sync_async = sync_to_async(_resume_run_sync)


async def resume_run_impl(run_id: str) -> None:
    """Resume a paused pipeline run."""
    await _resume_run_sync_async(run_id)
    await advance_pipeline_impl(run_id)


def _requeue_shards_sync(
    run: 'PipelineRun',
    stage_key: str,
    node: dict[str, Any],
    stage_cls: 'type[Any]',
    shard_indices: list[int],
) -> list[str]:
    """Queue fresh child executions for specific fan-out shards only.

    Reuses each shard's latest input_snapshot (same job, fresh attempt) and
    resets the fan-out parent off its terminal status so
    ``_maybe_complete_fan_out_parent`` re-aggregates once these children
    finish, instead of leaving it stuck on the old shard output.
    """
    from server.apps.pipelines.models import (  # noqa: PLC0415
        StageExecution,
        StageStatus,
    )

    parent = (
        StageExecution.objects
        .filter(run=run, stage_key=stage_key, parent=None)
        .order_by('-attempt')
        .first()
    )
    if parent is None:
        return []

    to_enqueue: list[str] = []
    for idx in shard_indices:
        latest_child = (
            StageExecution.objects
            .filter(run=run, stage_key=stage_key, shard_index=idx)
            .order_by('-attempt')
            .first()
        )
        if latest_child is None:
            continue
        child = StageExecution.objects.create(
            run=run,
            stage_key=stage_key,
            parent=parent,
            shard_index=idx,
            attempt=latest_child.attempt + 1,
            status=StageStatus.QUEUED,
            queue=node.get('queue', stage_cls.queue),
            max_retries=stage_cls.max_retries,
            input_snapshot=latest_child.input_snapshot,
            input_hash='',
        )
        to_enqueue.append(str(child.id))

    if to_enqueue and parent.status in {
        StageStatus.SUCCEEDED,
        StageStatus.FAILED,
        StageStatus.NEEDS_INPUT,
    }:
        parent.status = StageStatus.RUNNING
        parent.finished_at = None
        parent.save(update_fields=['status', 'finished_at'])

    return to_enqueue


def _rerun_stage_sync(
    run_id: str,
    stage_key: str,
    shard_indices: list[int] | None,
) -> list[str]:
    """Stale downstream stages and queue fresh attempt(s); return exec IDs.

    A whole-stage rerun (``shard_indices=None``) stales the stage itself
    plus everything downstream. A shard-scoped rerun only re-queues the
    requested fan-out children — sibling shards and their downstream
    consumers are left untouched, so re-rendering one bad scene doesn't
    blow away the rest of a fan-out batch.
    """
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
    # QUEUED is included so a lost/stuck message can be abandoned and a
    # fresh attempt enqueued; otherwise the old row stays QUEUED forever
    # and later advances skip it.
    terminal = {
        StageStatus.SUCCEEDED,
        StageStatus.FAILED,
        StageStatus.NEEDS_INPUT,
        StageStatus.SKIPPED,
        StageStatus.QUEUED,
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
        stale_keys = (
            downstream
            if shard_indices is not None
            else downstream | {stage_key}
        )

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

        if shard_indices is not None:
            to_enqueue = _requeue_shards_sync(
                run,
                stage_key,
                node,
                stage_cls,
                shard_indices,
            )
        else:
            qs = StageExecution.objects.filter(
                run=run,
                stage_key=stage_key,
                parent=None,
                shard_index__isnull=True,
            )
            latest_attempt = (
                qs
                .order_by('-attempt')
                .values_list('attempt', flat=True)
                .first()
            )
            next_attempt = (
                latest_attempt if latest_attempt is not None else -1
            ) + 1

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
            _seed_pending_downstream_sync(run, graph, downstream)

        if to_enqueue:
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
