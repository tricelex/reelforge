"""ClipApprovalGate stage — sentinel; orchestrator parks at AWAITING_REVIEW."""

from typing import Any, override

from server.apps.pipelines.stages.base import (
    Stage,
    StageContext,
    register_stage,
)


@register_stage
class ClipApprovalGateStage(Stage):
    """Gate sentinel for clip candidate review.

    The orchestrator detects ``gate: true`` nodes and parks the run at
    AWAITING_REVIEW without ever calling ``run()``. This class exists so
    the pipeline definition remains self-consistent.
    """

    key = 'clip_approval_gate'
    queue = 'api'
    max_retries = 0
    timeout_s = 1

    @override
    async def run(self, ctx: StageContext) -> dict[str, Any]:
        raise RuntimeError(
            'ClipApprovalGateStage.run() called directly — '
            'gates are handled by the orchestrator.',
        )
