"""ReviewGate stage — orchestrator parks runs; this class is a sentinel."""

from typing import Any, override

from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@register_stage
class ReviewGateStage(Stage):
    """Registered sentinel for the review_gate node.

    The orchestrator detects ``gate: true`` nodes and parks the run at
    AWAITING_REVIEW without ever calling execute_stage. This class exists so
    the pipeline definition remains self-consistent, but ``run()`` should
    never be called in normal operation.
    """

    key = 'review_gate'
    queue = 'api'
    max_retries = 0
    timeout_s = 1

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        raise RuntimeError(
            'ReviewGateStage.run() was called directly; '
            'gates are handled by the orchestrator (_park_gate_sync).',
        )
