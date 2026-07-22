"""FinalGate stage — orchestrator parks runs; sentinel only."""

from typing import Any, override

from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@register_stage
class FinalGateStage(Stage):
    """Registered sentinel for the final_gate node."""

    key = 'final_gate'
    queue = 'api'
    max_retries = 0
    timeout_s = 1

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        raise RuntimeError(
            'FinalGateStage.run() was called directly; '
            'gates are handled by the orchestrator (_park_gate_sync).',
        )
