"""Read-only queries for pipeline review gates."""

from decimal import Decimal

from server.apps.pipelines.models import (
    PipelineRun,
    RunStatus,
    StageExecution,
    StageStatus,
)


def _armed_gate_key(run: PipelineRun, gate: StageExecution) -> bool:
    armed = set(run.channel.gates or [])
    return not armed or gate.stage_key in armed


def count_gates_waiting() -> int:
    """Count runs parked at armed review gates."""
    return len(list_gates_waiting())


def list_gates_waiting() -> list[dict[str, object]]:
    """Return waiting gate rows for the operator queue."""
    runs = (
        PipelineRun.objects
        .filter(status=RunStatus.AWAITING_REVIEW)
        .select_related('channel')
        .order_by('-updated_at')
    )
    items: list[dict[str, object]] = []
    for run in runs:
        gate = (
            StageExecution.objects
            .filter(run=run, parent=None, status=StageStatus.RUNNING)
            .order_by('-created_at')
            .first()
        )
        if gate is None or not _armed_gate_key(run, gate):
            continue
        items.append(
            {
                'run_id': str(run.id),
                'gate_key': gate.stage_key,
                'channel_name': run.channel.name,
                'topic': run.topic,
                'spent_usd': f'{run.total_cost_usd:.4f}',
            },
        )
    return items
